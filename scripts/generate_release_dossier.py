#!/usr/bin/env python3
"""
Release Dossier Generator for MERID Season 1.

Creates comprehensive release dossiers that tie together code, tests, security scans,
and runtime behavior for regulatory compliance.
"""

import json
import argparse
import sys
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List
import hashlib

class ReleaseDossierGenerator:
    """Generates comprehensive release dossiers for regulatory compliance."""
    
    def __init__(self, version: str, pipeline_url: str):
        self.version = version
        self.pipeline_url = pipeline_url
        self.dossier_id = hashlib.sha256(f"{version}_{pipeline_url}".encode()).hexdigest()[:16]
        self.dossier_data = {
            "release_metadata": {
                "version": version,
                "pipeline_url": pipeline_url,
                "dossier_id": self.dossier_id,
                "timestamp": datetime.utcnow().isoformat(),
                "environment": os.getenv("ENVIRONMENT", "production"),
                "release_type": "production",
                "season": "1"
            },
            "code_changes": {},
            "security_scan_results": {},
            "risk_control_validation": {},
            "runtime_primitive_behavior": {},
            "compliance_attestation": {},
            "deployment_artifacts": {},
            "post_deployment_monitoring": {},
            "stakeholder_notifications": {},
            "regulatory_findings": {}
        }
    
    def add_code_changes(self, git_changes: Dict, pr_metadata: Dict):
        """Add code changes information."""
        self.dossier_data["code_changes"] = {
            "commit_hash": git_changes.get("commit_hash", ""),
            "branch": git_changes.get("branch", ""),
            "author": git_changes.get("author", ""),
            "timestamp": git_changes.get("timestamp", ""),
            "files_changed": git_changes.get("files_changed", []),
            "lines_added": git_changes.get("lines_added", 0),
            "lines_removed": git_changes.get("lines_removed", 0),
            "pr_number": pr_metadata.get("number", ""),
            "pr_title": pr_metadata.get("title", ""),
            "pr_description": pr_metadata.get("description", ""),
            "reviewers": pr_metadata.get("reviewers", []),
            "approvals": pr_metadata.get("approvals", [])
        }
    
    def add_security_scan_results(self, scan_results: Dict):
        """Add comprehensive security scan results."""
        self.dossier_data["security_scan_results"] = {
            "trivy": scan_results.get("trivy", {}),
            "snyk": scan_results.get("snyk", {}),
            "codeql": scan_results.get("codeql", {}),
            "secrets": scan_results.get("secrets", {}),
            "container_security": scan_results.get("container_security", {}),
            "policy_validation": scan_results.get("policy_validation", {}),
            "overall_security_status": scan_results.get("overall_status", "unknown"),
            "critical_vulnerabilities": scan_results.get("critical_count", 0),
            "high_vulnerabilities": scan_results.get("high_count", 0),
            "security_scan_timestamp": datetime.utcnow().isoformat()
        }
    
    def add_risk_control_validation(self, validation_results: Dict):
        """Add risk control validation results."""
        self.dossier_data["risk_control_validation"] = {
            "runtime_primitive_tests": validation_results.get("runtime_primitive_tests", {}),
            "domain_priority_tests": validation_results.get("domain_priority_tests", {}),
            "sighted_degraded_activation": validation_results.get("sighted_degraded_activation", {}),
            "conflict_resolution": validation_results.get("conflict_resolution", {}),
            "degraded_signal_handling": validation_results.get("degraded_signal_handling", {}),
            "fault_injection_tests": validation_results.get("fault_injection_tests", {}),
            "overall_risk_status": validation_results.get("overall_status", "unknown"),
            "safety_check_failures": validation_results.get("safety_check_failures", []),
            "priority_violations": validation_results.get("priority_violations", 0),
            "mode_transitions": validation_results.get("mode_transitions", []),
            "risk_validation_timestamp": datetime.utcnow().isoformat()
        }
    
    def add_runtime_primitive_behavior(self, behavior_data: Dict):
        """Add runtime primitive behavior data."""
        self.dossier_data["runtime_primitive_behavior"] = {
            "mode_transitions": behavior_data.get("mode_transitions", []),
            "assertion_health": behavior_data.get("assertion_health", {}),
            "domain_priority_enforcement": behavior_data.get("domain_priority_enforcement", {}),
            "safety_check_performance": behavior_data.get("safety_check_performance", {}),
            "priority_violation_patterns": behavior_data.get("priority_violation_patterns", []),
            "system_stability_metrics": behavior_data.get("stability_metrics", {}),
            "behavior_analysis_timestamp": datetime.utcnow().isoformat()
        }
    
    def add_compliance_attestation(self, compliance_data: Dict):
        """Add compliance attestation data."""
        self.dossier_data["compliance_attestation"] = {
            "sox_compliance": compliance_data.get("sox_compliance", {}),
            "data_retention": compliance_data.get("data_retention", {}),
            "audit_trail_integrity": compliance_data.get("audit_trail_integrity", {}),
            "access_control_compliance": compliance_data.get("access_control_compliance", {}),
            "regulatory_reporting": compliance_data.get("regulatory_reporting", {}),
            "risk_management": compliance_data.get("risk_management", {}),
            "overall_compliance_status": compliance_data.get("overall_status", "unknown"),
            "compliance_attestation_timestamp": datetime.utcnow().isoformat(),
            "attestation_signoff": compliance_data.get("signoff", {})
        }
    
    def add_deployment_artifacts(self, artifacts: Dict):
        """Add deployment artifacts."""
        self.dossier_data["deployment_artifacts"] = {
            "docker_image": artifacts.get("docker_image", {}),
            "helm_chart": artifacts.get("helm_chart", {}),
            "configuration": artifacts.get("configuration", {}),
            "test_results": artifacts.get("test_results", {}),
            "monitoring_dashboards": artifacts.get("monitoring_dashboards", {}),
            "infrastructure_as_code": artifacts.get("infrastructure_as_code", {}),
            "artifact_timestamp": datetime.utcnow().isoformat()
        }
    
    def add_post_deployment_monitoring(self, monitoring_data: Dict):
        """Add post-deployment monitoring data."""
        self.dossier_data["post_deployment_monitoring"] = {
            "initial_health_status": monitoring_data.get("initial_health", {}),
            "performance_metrics": monitoring_data.get("performance_metrics", {}),
            "error_rates": monitoring_data.get("error_rates", {}),
            "resource_utilization": monitoring_data.get("resource_utilization", {}),
            "security_events": monitoring_data.get("security_events", []),
            "compliance_alerts": monitoring_data.get("compliance_alerts", []),
            "monitoring_period": monitoring_data.get("monitoring_period", "24h"),
            "monitoring_timestamp": datetime.utcnow().isoformat()
        }
    
    def add_stakeholder_notifications(self, notifications: Dict):
        """Add stakeholder notifications."""
        self.dossier_data["stakeholder_notifications"] = {
            "executive_summary": notifications.get("executive_summary", {}),
            "technical_summary": notifications.get("technical_summary", {}),
            "compliance_summary": notifications.get("compliance_summary", {}),
            "operations_summary": notifications.get("operations_summary", {}),
            "risk_summary": notifications.get("risk_summary", {}),
            "notification_timestamp": datetime.utcnow().isoformat(),
            "notification_channels": notifications.get("channels", [])
        }
    
    def add_regulatory_findings(self, findings: Dict):
        """Add regulatory findings and recommendations."""
        self.dossier_data["regulatory_findings"] = {
            "identified_risks": findings.get("identified_risks", []),
            "mitigation_measures": findings.get("mitigation_measures", []),
            "recommendations": findings.get("recommendations", []),
            "regulatory_references": findings.get("regulatory_references", []),
            "findings_timestamp": datetime.utcnow().isoformat()
        }
    
    def calculate_compliance_score(self) -> float:
        """Calculate overall compliance score."""
        scores = []
        
        # Security compliance score (40% weight)
        security_score = 0.0
        if self.dossier_data["security_scan_results"]["overall_security_status"] == "passed":
            security_score = 100.0
        elif self.dossier_data["security_scan_results"]["overall_security_status"] == "warning":
            security_score = 75.0
        else:
            security_score = 0.0
        
        # Deduct points for vulnerabilities
        critical_vulns = self.dossier_data["security_scan_results"]["critical_vulnerabilities"]
        high_vulns = self.dossier_data["security_scan_results"]["high_vulnerabilities"]
        security_score -= (critical_vulns * 10 + high_vulns * 5)
        security_score = max(0.0, security_score)
        scores.append(("security", security_score, 0.4))
        
        # Risk control validation score (30% weight)
        risk_score = 0.0
        if self.dossier_data["risk_control_validation"]["overall_risk_status"] == "passed":
            risk_score = 100.0
        elif self.dossier_data["risk_control_validation"]["overall_risk_status"] == "warning":
            risk_score = 80.0
        else:
            risk_score = 0.0
        
        # Deduct points for safety check failures
        safety_failures = len(self.dossier_data["risk_control_validation"]["safety_check_failures"])
        risk_score -= (safety_failures * 15)
        priority_violations = self.dossier_data["risk_control_validation"]["priority_violations"]
        risk_score -= (priority_violations * 2)
        risk_score = max(0.0, risk_score)
        scores.append(("risk_control", risk_score, 0.3))
        
        # Compliance attestation score (30% weight)
        compliance_score = 0.0
        if self.dossier_data["compliance_attestation"]["overall_compliance_status"] == "compliant":
            compliance_score = 100.0
        elif self.dossier_data["compliance_attestation"]["overall_compliance_status"] == "partially_compliant":
            compliance_score = 85.0
        else:
            compliance_score = 0.0
        
        scores.append(("compliance", compliance_score, 0.3))
        
        # Calculate weighted average
        total_score = sum(score * weight for name, score, weight in scores)
        
        return total_score
    
    def save_report(self, output_path: str):
        """Save dossier in both JSON and HTML formats."""
        # Generate JSON dossier
        json_dossier = self.generate_json_dossier()
        json_path = output_path.replace('.html', '.json')
        
        # Save JSON dossier
        with open(json_path, 'w') as f:
            f.write(json_dossier)
        
        # Generate HTML dossier
        html_dossier = self.generate_html_dossier()
        
        # Save HTML dossier
        with open(output_path, 'w') as f:
            f.write(html_dossier)
    
    def generate_release_dossier(self) -> Dict[str, Any]:
        """Generate complete release dossier."""
        # Calculate compliance score
        compliance_score = self.calculate_compliance_score()
        self.dossier_data["compliance_score"] = compliance_score
        
        # Determine overall status
        if compliance_score >= 90:
            overall_status = "APPROVED_FOR_PRODUCTION"
        elif compliance_score >= 75:
            overall_status = "APPROVED_WITH_CONDITIONS"
        elif compliance_score >= 50:
            overall_status = "NEEDS_REVIEW"
        else:
            overall_status = "REJECTED"
        
        self.dossier_data["overall_status"] = overall_status
        self.dossier_data["compliance_score"] = compliance_score
        self.dossier_data["dossier_timestamp"] = datetime.utcnow().isoformat()
        
        return self.dossier_data
    
    def generate_json_dossier(self) -> str:
        """Generate JSON release dossier."""
        dossier = self.generate_release_dossier()
        return json.dumps(dossier, indent=2)
    
    def generate_html_dossier(self) -> str:
        """Generate HTML release dossier."""
        dossier = self.generate_release_dossier()
        compliance_score = dossier["compliance_score"]
        overall_status = dossier["overall_status"]
        
        status_color = {
            "APPROVED_FOR_PRODUCTION": "#28a745",
            "APPROVED_WITH_CONDITIONS": "#ffc107",
            "NEEDS_REVIEW": "#fd7e14",
            "REJECTED": "#dc3545"
        }.get(overall_status, "#6c757d")
        
        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MERID Release Dossier - {self.version} (Season 1)</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f8f9fa;
            color: #333;
        }}
        .container {{
            max-width: 1400px;
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
        .status {{
            font-size: 28px;
            font-weight: bold;
            color: {status_color};
            padding: 15px 30px;
            border-radius: 8px;
            display: inline-block;
            margin-bottom: 10px;
            text-transform: uppercase;
        }}
        .compliance-score {{
            font-size: 18px;
            font-weight: bold;
            color: #28a745;
            margin-bottom: 10px;
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
            padding: 12px 0;
            border-bottom: 1px solid #eee;
            align-items: center;
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
        .finding {{
            background: #f8f9fa;
            border-left: 4px solid #007bff;
            padding: 15px;
            margin-bottom: 10px;
            border-radius: 4px;
        }}
        .finding.critical {{
            border-left-color: #dc3545;
        }}
        .finding.high {{
            border-left-color: #fd7e14;
        }}
        .finding.medium {{
            border-left-color: #ffc107;
        }}
        .priority {{
            font-weight: bold;
            text-transform: uppercase;
            font-size: 12px;
            margin-bottom: 5px;
        }}
        .timestamp {{
            color: #666;
            font-size: 12px;
        }}
        .summary {{
            background: #e9ecef;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }}
        .summary h3 {{
            margin-top: 0;
            color: #333;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
            text-transform: uppercase;
        }}
        .badge.approved {{
            background: #28a745;
            color: white;
        }}
        .badge.rejected {{
            background: #dc3545;
            color: white;
        }}
        .badge.warning {{
            background: #ffc107;
            color: #212529;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}
        .card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .card h3 {{
            margin-top: 0;
            color: #333;
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
            <h1>MERID Release Dossier</h1>
            <div class="status">{overall_status}</div>
            <div class="compliance-score">Compliance Score: {compliance_score:.1f}%</div>
            <div class="timestamp">Dossier ID: {self.dossier_id}</div>
            <p>Version: {self.version} | Season 1 | Environment: {self.dossier_data['release_metadata']['environment']}</p>
            <p>Timestamp: {self.dossier_data['release_metadata']['timestamp']}</p>
            <p>Pipeline: <a href="{self.pipeline_url}">View Pipeline</a></p>
        </div>
        
        <div class="summary">
            <h3>Executive Summary</h3>
            <p><strong>Status:</strong> <span class="badge {overall_status.lower()}">{overall_status}</span></p>
            <p><strong>Compliance Score:</strong> {compliance_score:.1f}%</p>
            <p><strong>Security Status:</strong> <span class="status-{self.dossier_data['security_scan_results']['overall_security_status'].lower()}">{self.dossier_data['security_scan_results']['overall_security_status'].upper()}</span></p>
            <p><strong>Risk Control:</strong> <span class="status-{self.dossier_data['risk_control_validation']['overall_risk_status'].lower()}">{self.dossier_data['risk_control_validation']['overall_risk_status'].upper()}</span></p>
            <p><strong>Compliance:</strong> <span class="status-{self.dossier_data['compliance_attestation']['overall_compliance_status'].lower()}">{self.dossier_data['compliance_attestation']['overall_compliance_status'].upper()}</span></p>
        </div>
        
        <div class="grid">
            <div class="card">
                <h3>Security Scan Results</h3>
                <div class="metric">
                    <span class="metric-label">Overall Status:</span>
                    <span class="metric-value status-{self.dossier_data['security_scan_results']['overall_security_status'].lower()}">
                        {self.dossier_data['security_scan_results']['overall_security_status'].upper()}
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">Critical Vulnerabilities:</span>
                    <span class="metric-value">{self.dossier_data['security_scan_results']['critical_vulnerabilities']}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">High Vulnerabilities:</span>
                    <span class="metric-value">{self.dossier_data['security_scan_results']['high_vulnerabilities']}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Secrets Found:</span>
                    <span class="metric-value">{self.dossier_data['security_scan_results']['secrets'].get('critical_count', 0)}</span>
                </div>
            </div>
            
            <div class="card">
                <h3>Risk Control Validation</h3>
                <div class="metric">
                    <span class="metric-label">Overall Status:</span>
                    <span class="metric-value status-{self.dossier_data['risk_control_validation']['overall_risk_status'].lower()}">
                        {self.dossier_data['risk_control_validation']['overall_risk_status'].upper()}
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">Safety Check Failures:</span>
                    <span class="metric-value">{len(self.dossier_data['risk_control_validation']['safety_check_failures'])}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Priority Violations:</span>
                    <span class="metric-value">{self.dossier_data['risk_control_validation']['priority_violations']}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Mode Transitions:</span>
                    <span class="metric-value">{self.dossier_data['risk_control_validation']['mode_transitions']}</span>
                </div>
            </div>
            
            <div class="card">
                <h3>Compliance Attestation</h3>
                <div class="metric">
                    <span class="metric-label">Overall Status:</span>
                    <span class="metric-value status-{self.dossier_data['compliance_attestation']['overall_compliance_status'].lower()}">
                        {self.dossier_data['compliance_attestation']['overall_compliance_status'].upper()}
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">SOX Compliance:</span>
                    <span class="metric-value status-{'compliant' if self.dossier_data['compliance_attestation']['sox_compliance'].get('compliant', False) else 'non_compliant'}">
                        {'COMPLIANT' if self.dossier_data['compliance_attestation']['sox_compliance'].get('compliant', False) else 'NON_COMPLIANT'}
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">Audit Trail:</span>
                    <span class="metric-value status-{'compliant' if self.dossier_data['compliance_attestation']['audit_trail_integrity'].get('compliant', False) else 'non_compliant'}">
                        {'COMPLIANT' if self.dossier_data['compliance_attestation']['audit_trail_integrity'].get('compliant', False) else 'NON_COMPLIANT'}
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">Access Control:</span>
                    <span class="metric-value status-{'compliant' if self.dossier_data['compliance_attestation']['access_control_compliance'].get('compliant', False) else 'non_compliant'}">
                        {'COMPLIANT' if self.dossier_data['compliance_attestation']['access_control_compliance'].get('compliant', False) else 'NON_COMPLIANT'}
                    </span>
                </div>
            </div>
        </div>
        
        <div class="section">
            <h2>Regulatory Findings & Recommendations</h2>
            {self._generate_findings_html()}
        </div>
        
        <div class="section">
            <h2>Stakeholder Notifications</h2>
            <div class="metric">
                <span class="metric-label">Executive Summary:</span>
                <span class="metric-value">{self.dossier_data['stakeholder_notifications'].get('executive_summary', {}).get('status', 'pending')}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Technical Summary:</span>
                <span class="metric-value">{self.dossier_data['stakeholder_notifications'].get('technical_summary', {}).get('status', 'pending')}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Compliance Summary:</span>
                <span class="metric-value">{self.dossier_data['stakeholder_notifications'].get('compliance_summary', {}).get('status', 'pending')}</span>
            </div>
        </div>
        
        <div class="download-links">
            <a href="release-dossier-{self.version}.json" download>Download JSON Dossier</a>
            <a href="release-dossier-{self.version}.html" download>Download HTML Report</a>
            <a href="{self.pipeline_url}" target="_blank">View Pipeline Run</a>
        </div>
    </div>
</body>
</html>
        """
        return html
    
    def _generate_findings_html(self) -> str:
        """Generate HTML for regulatory findings."""
        findings = self.dossier_data["regulatory_findings"]
        
        html_parts = []
        
        # Identified risks
        for risk in findings.get("identified_risks", []):
            html_parts.append(f"""
            <div class="finding critical">
                <div class="priority">Risk</div>
                <div><strong>{risk.get('title', 'Unknown Risk')}</strong></div>
                <div>{risk.get('description', 'No description available')}</div>
                <div><strong>Mitigation:</strong> {risk.get('mitigation', 'No mitigation available')}</div>
                <div><strong>Reference:</strong> {risk.get('reference', 'No reference available')}</div>
            </div>
            """)
        
        # Mitigation measures
        for mitigation in findings.get("mitigation_measures", []):
            html_parts.append(f"""
            <div class="finding high">
                <div class="priority">Mitigation</div>
                <div><strong>{mitigation.get('title', 'Unknown Mitigation')}</strong></div>
                <div>{mitigation.get('description', 'No description available')}</div>
                <div><strong>Status:</strong> {mitigation.get('status', 'pending')}</div>
            </div>
            """)
        
        # Recommendations
        for recommendation in findings.get("recommendations", []):
            html_parts.append(f"""
            <div class="finding medium">
                <div class="priority">Recommendation</div>
                <div><strong>{recommendation.get('title', 'Unknown Recommendation')}</strong></div>
                <div>{recommendation.get('description', 'No description available')}</div>
                <div><strong>Priority:</strong> {recommendation.get('priority', 'medium')}</div>
            </div>
            """)
        
        return "".join(html_parts)


def main():
    """Main entry point for release dossier generation."""
    parser = argparse.ArgumentParser(description='Generate MERID release dossier')
    parser.add_argument('--version', required=True, help='Release version')
    parser.add_argument('--pipeline-url', required=True, help='Pipeline URL')
    parser.add_argument('--output', default='release-dossier.html', help='Output filename')
    
    args = parser.parse_args()
    
    # Create dossier generator
    generator = ReleaseDossierGenerator(args.version, args.pipeline_url)
    
    # Mock data for demonstration (in real implementation, this would come from actual pipeline)
    git_changes = {
        "commit_hash": "abc123",
        "branch": "main",
        "author": "developer@merid.com",
        "timestamp": datetime.utcnow().isoformat(),
        "files_changed": ["core/domain_priority_manager.py", "core/reality_auditor.py"],
        "lines_added": 150,
        "lines_removed": 25
    }
    
    pr_metadata = {
        "number": "123",
        "title": "Add domain priority system enhancements",
        "description": "Enhanced conflict resolution and safety checks",
        "reviewers": ["senior-developer@merid.com", "security@merid.com"],
        "approvals": 2
    }
    
    scan_results = {
        "trivy": {"critical_count": 0, "high_count": 2, "scan_passed": True},
        "snyk": {"critical_count": 0, "high_count": 1, "scan_passed": True},
        "codeql": {"critical_count": 0, "high_count": 0, "scan_passed": True},
        "secrets": {"critical_count": 0, "high_count": 0, "scan_passed": True},
        "container_security": {"critical_count": 0, "high_count": 1, "scan_passed": True},
        "policy_validation": {"scan_passed": True},
        "overall_status": "passed"
    }
    
    validation_results = {
        "runtime_primitive_tests": {"passed": True, "test_count": 45},
        "domain_priority_tests": {"passed": True, "test_count": 25},
        "sighted_degraded_activation": {"passed": True, "test_count": 15},
        "conflict_resolution": {"passed": True, "test_count": 30},
        "degraded_signal_handling": {"passed": True, "test_count": 20},
        "fault_injection_tests": {"passed": True, "test_count": 35},
        "overall_status": "passed",
        "safety_check_failures": [],
        "priority_violations": 0,
        "mode_transitions": 2
    }
    
    behavior_data = {
        "mode_transitions": [
            {"timestamp": "2024-01-20T10:00:00Z", "from": "BLIND", "to": "SIGHTED_DEGRADED", "reason": "Production threshold met"},
            {"timestamp": "2024-01-20T10:05:00Z", "from": "SIGHTED_DEGRADED", "to": "BLIND", "reason": "Safety check failure"}
        ],
        "assertion_health": {
            "valid_assertions": 28,
            "total_assertions": 28,
            "health_score": 95.0
        },
        "domain_priority_enforcement": {
            "access_denied_count": 15,
            "violation_rate": 0.02,
            "enforcement_accuracy": 100.0
        },
        "safety_check_performance": {
            "avg_latency_ms": 15.5,
            "p95_latency_ms": 25.0,
            "success_rate": 99.8
        },
        "priority_violation_patterns": [],
        "stability_metrics": {
            "uptime_percentage": 99.9,
            "error_rate": 0.1,
            "resource_utilization": 65.0
        }
    }
    
    compliance_data = {
        "sox_compliance": {"compliant": True, "findings": [], "last_audit": "2024-01-20T10:00:00Z"},
        "data_retention": {"compliant": True, "retention_period_days": 2555},
        "audit_trail_integrity": {"compliant": True, "last_verification": "2024-01-20T10:00:00Z"},
        "access_control_compliance": {"compliant": True, "least_privilege": True, "access_logs": "complete"},
        "regulatory_reporting": {"compliant": True, "last_report": "2024-01-20T10:00:00Z"},
        "risk_management": {"compliant": True, "risk_assessments": "current"},
        "overall_status": "compliant",
        "signoff": {
            "security_lead": "security@merid.com",
            "compliance_officer": "compliance@merid.com",
            "timestamp": "2024-01-20T10:00:00Z"
        }
    }
    
    artifacts = {
        "docker_image": {"tag": f"merid:{args.version}", "digest": "sha256:abc123"},
        "helm_chart": {"version": "1.0.0", "appVersion": args.version},
        "configuration": {"environment": "production", "featureFlags": {"runtime_primitive_enabled": True}},
        "test_results": {"total": 120, "passed": 120, "failed": 0, "skipped": 0},
        "monitoring_dashboards": ["https://grafana.merid.com/d/merid-production"],
        "infrastructure_as_code": {"terraform": "validated", "k8s": "validated"},
        "artifact_timestamp": datetime.utcnow().isoformat()
    }
    
    monitoring_data = {
        "initial_health": {"status": "healthy", "timestamp": "2024-01-20T10:00:00Z"},
        "performance_metrics": {"avg_response_time_ms": 45.2, "p95_response_time_ms": 78.5, "error_rate": 0.02},
        "error_rates": {"4xx": 0, "5xx": 0},
        "resource_utilization": {"cpu": 65.0, "memory": 45.0, "disk": 30.0},
        "security_events": [],
        "compliance_alerts": [],
        "monitoring_period": "24h"
    }
    
    notifications = {
        "executive_summary": {"status": "sent", "timestamp": "2024-01-20T10:00:00Z"},
        "technical_summary": {"status": "sent", "timestamp": "2024-01-20T10:00:00Z"},
        "compliance_summary": {"status": "sent", "timestamp": "2024-01-20T10:00:00Z"},
        "operations_summary": {"status": "sent", "timestamp": "2024-01-20T10:00:00Z"},
        "risk_summary": {"status": "sent", "timestamp": "2024-01-20T10:00:00Z"},
        "channels": ["email", "slack"]
    }
    
    findings = {
        "identified_risks": [
            {
                "title": "No critical vulnerabilities detected",
                "description": "Security scans show no critical vulnerabilities",
                "mitigation": "Continue regular security scanning",
                "reference": "FINRA Automated Trading Risk Controls",
                "priority": "low"
            }
        ],
        "mitigation_measures": [
            {
                "title": "Regular security scanning implemented",
                "description": "Automated security scanning in CI/CD pipeline",
                "status": "active",
                "priority": "medium"
            }
        ],
        "recommendations": [
            {
                "title": "Enhanced monitoring coverage",
                "description": "Add more granular metrics for domain priority system",
                "priority": "medium"
            }
        ],
        "regulatory_references": [
            "FINRA Automated Trading Risk Controls",
            "SOX Compliance Requirements",
            "SEC Cybersecurity Guidelines"
        ]
    }
    
    # Add all data to dossier
    generator.add_code_changes(git_changes, pr_metadata)
    generator.add_security_scan_results(scan_results)
    generator.add_risk_control_validation(validation_results)
    generator.add_runtime_primitive_behavior(behavior_data)
    generator.add_compliance_attestation(compliance_data)
    generator.add_deployment_artifacts(artifacts)
    generator.add_post_deployment_monitoring(monitoring_data)
    generator.add_stakeholder_notifications(notifications)
    generator.add_regulatory_findings(findings)
    
    # Generate and save dossier
    generator.save_report(args.output)
    
    print(f"Release dossier generated: {args.output}")
    print(f"JSON dossier saved: {args.output.replace('.html', '.json')}")
    print(f"Compliance Score: {generator.calculate_compliance_score():.1f}%")
    print(f"Overall Status: {generator.calculate_compliance_score():.1f}% - {generator.dossier_data['overall_status']}")


if __name__ == "__main__":
    main()
