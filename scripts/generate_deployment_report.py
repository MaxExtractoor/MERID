#!/usr/bin/env python3
"""
Generate Deployment Report for MERID Production Pipeline.

Creates comprehensive deployment report with security scan results,
test results, and compliance information.
"""

import json
import argparse
import sys
from datetime import datetime
from typing import Dict, Any, List
import os

class DeploymentReportGenerator:
    """Generates comprehensive deployment reports."""
    
    def __init__(self, version: str, pipeline_url: str):
        self.version = version
        self.pipeline_url = pipeline_url
        self.report_data = {
            "deployment_info": {
                "version": version,
                "pipeline_url": pipeline_url,
                "timestamp": datetime.utcnow().isoformat(),
                "environment": os.getenv("ENVIRONMENT", "unknown")
            },
            "security_scan_results": {},
            "test_results": {},
            "runtime_primitive_validation": {},
            "compliance_status": {},
            "metrics": {},
            "recommendations": []
        }
    
    def add_security_scan_results(self, trivy_results: Dict, snyk_results: Dict, 
                                codeql_results: Dict, secrets_results: Dict):
        """Add security scan results to report."""
        self.report_data["security_scan_results"] = {
            "trivy": {
                "vulnerabilities": trivy_results.get("vulnerabilities", []),
                "critical_count": trivy_results.get("critical_count", 0),
                "high_count": trivy_results.get("high_count", 0),
                "scan_passed": trivy_results.get("scan_passed", False)
            },
            "snyk": {
                "vulnerabilities": snyk_results.get("vulnerabilities", []),
                "critical_count": snyk_results.get("critical_count", 0),
                "high_count": snyk_results.get("high_count", 0),
                "scan_passed": snyk_results.get("scan_passed", False)
            },
            "codeql": {
                "alerts": codeql_results.get("alerts", []),
                "critical_count": codeql_results.get("critical_count", 0),
                "high_count": codeql_results.get("high_count", 0),
                "scan_passed": codeql_results.get("scan_passed", False)
            },
            "secrets": {
                "findings": secrets_results.get("findings", []),
                "critical_count": secrets_results.get("critical_count", 0),
                "high_count": secrets_results.get("high_count", 0),
                "scan_passed": secrets_results.get("scan_passed", False)
            }
        }
        
        # Calculate overall security status
        security_passed = all([
            self.report_data["security_scan_results"]["trivy"]["scan_passed"],
            self.report_data["security_scan_results"]["snyk"]["scan_passed"],
            self.report_data["security_scan_results"]["codeql"]["scan_passed"],
            self.report_data["security_scan_results"]["secrets"]["scan_passed"]
        ])
        
        self.report_data["security_scan_results"]["overall_passed"] = security_passed
        
        # Add recommendations based on findings
        self._generate_security_recommendations()
    
    def add_test_results(self, unit_test_results: Dict, integration_test_results: Dict,
                         e2e_test_results: Dict):
        """Add test results to report."""
        self.report_data["test_results"] = {
            "unit_tests": {
                "total": unit_test_results.get("total", 0),
                "passed": unit_test_results.get("passed", 0),
                "failed": unit_test_results.get("failed", 0),
                "skipped": unit_test_results.get("skipped", 0),
                "coverage": unit_test_results.get("coverage", 0.0),
                "passed": unit_test_results.get("passed", 0) == unit_test_results.get("total", 0)
            },
            "integration_tests": {
                "total": integration_test_results.get("total", 0),
                "passed": integration_test_results.get("passed", 0),
                "failed": integration_test_results.get("failed", 0),
                "skipped": integration_test_results.get("skipped", 0),
                "passed": integration_test_results.get("passed", 0) == integration_test_results.get("total", 0)
            },
            "e2e_tests": {
                "total": e2e_test_results.get("total", 0),
                "passed": e2e_test_results.get("passed", 0),
                "failed": e2e_test_results.get("failed", 0),
                "skipped": e2e_test_results.get("skipped", 0),
                "passed": e2e_test_results.get("passed", 0) == e2e_test_results.get("total", 0)
            }
        }
        
        # Calculate overall test status
        tests_passed = all([
            self.report_data["test_results"]["unit_tests"]["passed"],
            self.report_data["test_results"]["integration_tests"]["passed"],
            self.report_data["test_results"]["e2e_tests"]["passed"]
        ])
        
        self.report_data["test_results"]["overall_passed"] = tests_passed
        
        # Add recommendations based on test results
        self._generate_test_recommendations()
    
    def add_runtime_primitive_validation(self, validation_results: Dict):
        """Add runtime primitive validation results."""
        self.report_data["runtime_primitive_validation"] = {
            "sighted_degraded_activation": validation_results.get("sighted_degraded_activation", {}),
            "domain_priority_system": validation_results.get("domain_priority_system", {}),
            "conflict_resolution": validation_results.get("conflict_resolution", {}),
            "degraded_signal_handling": validation_results.get("degraded_signal_handling", {}),
            "fault_injection": validation_results.get("fault_injection", {}),
            "overall_passed": validation_results.get("overall_passed", False)
        }
        
        # Add recommendations based on validation results
        self._generate_runtime_primitive_recommendations()
    
    def add_compliance_status(self, compliance_results: Dict):
        """Add compliance status to report."""
        self.report_data["compliance_status"] = {
            "sox_compliance": compliance_results.get("sox_compliance", {}),
            "data_retention": compliance_results.get("data_retention", {}),
            "audit_trail": compliance_results.get("audit_trail", {}),
            "access_control": compliance_results.get("access_control", {}),
            "overall_compliant": compliance_results.get("overall_compliant", False)
        }
        
        # Add recommendations based on compliance results
        self._generate_compliance_recommendations()
    
    def add_metrics(self, metrics: Dict):
        """Add production metrics to report."""
        self.report_data["metrics"] = metrics
    
    def _generate_security_recommendations(self):
        """Generate security recommendations based on scan results."""
        recommendations = []
        
        security_results = self.report_data["security_scan_results"]
        
        # Trivy recommendations
        if not security_results["trivy"]["scan_passed"]:
            if security_results["trivy"]["critical_count"] > 0:
                recommendations.append({
                    "priority": "CRITICAL",
                    "category": "Security",
                    "title": "Critical Vulnerabilities Found",
                    "description": f"Trivy found {security_results['trivy']['critical_count']} critical vulnerabilities that must be fixed before deployment.",
                    "action": "Fix all critical vulnerabilities and rescan."
                })
            
            if security_results["trivy"]["high_count"] > 0:
                recommendations.append({
                    "priority": "HIGH",
                    "category": "Security",
                    "title": "High Severity Vulnerabilities",
                    "description": f"Trivy found {security_results['trivy']['high_count']} high severity vulnerabilities.",
                    "action": "Address high severity vulnerabilities in next release."
                })
        
        # Snyk recommendations
        if not security_results["snyk"]["scan_passed"]:
            if security_results["snyk"]["critical_count"] > 0:
                recommendations.append({
                    "priority": "CRITICAL",
                    "category": "Security",
                    "title": "Critical Dependency Vulnerabilities",
                    "description": f"Snyk found {security_results['snyk']['critical_count']} critical dependency vulnerabilities.",
                    "action": "Update vulnerable dependencies immediately."
                })
        
        # CodeQL recommendations
        if not security_results["codeql"]["scan_passed"]:
            recommendations.append({
                "priority": "HIGH",
                "category": "Security",
                "title": "Code Security Issues",
                "description": f"CodeQL found {security_results['codeql']['critical_count']} critical and {security_results['codeql']['high_count']} high severity issues.",
                "action": "Address CodeQL security issues before deployment."
            })
        
        # Secrets recommendations
        if not security_results["secrets"]["scan_passed"]:
            recommendations.append({
                "priority": "CRITICAL",
                "category": "Security",
                "title": "Secrets Detected in Code",
                "description": f"Secrets scanner found {security_results['secrets']['critical_count']} critical and {security_results['secrets']['high_count']} high severity secrets.",
                "action": "Remove all secrets from code repository immediately."
            })
        
        self.report_data["recommendations"].extend(recommendations)
    
    def _generate_test_recommendations(self):
        """Generate test recommendations based on test results."""
        recommendations = []
        
        test_results = self.report_data["test_results"]
        
        # Unit test recommendations
        if not test_results["unit_tests"]["passed"]:
            if test_results["unit_tests"]["failed"] > 0:
                recommendations.append({
                    "priority": "HIGH",
                    "category": "Testing",
                    "title": "Unit Test Failures",
                    "description": f"{test_results['unit_tests']['failed']} unit tests failed.",
                    "action": "Fix failing unit tests before deployment."
                })
            
            if test_results["unit_tests"]["coverage"] < 90:
                recommendations.append({
                    "priority": "MEDIUM",
                    "category": "Testing",
                    "title": "Low Test Coverage",
                    "description": f"Unit test coverage is {test_results['unit_tests']['coverage']:.1f}%, below 90% threshold.",
                    "action": "Improve test coverage to meet 90% threshold."
                })
        
        # Integration test recommendations
        if not test_results["integration_tests"]["passed"]:
            recommendations.append({
                "priority": "HIGH",
                "category": "Testing",
                "title": "Integration Test Failures",
                "description": f"{test_results['integration_tests']['failed']} integration tests failed.",
                "action": "Fix failing integration tests before deployment."
            })
        
        # E2E test recommendations
        if not test_results["e2e_tests"]["passed"]:
            recommendations.append({
                "priority": "HIGH",
                "category": "Testing",
                "title": "E2E Test Failures",
                "description": f"{test_results['e2e_tests']['failed']} end-to-end tests failed.",
                "action": "Fix failing E2E tests before deployment."
            })
        
        self.report_data["recommendations"].extend(recommendations)
    
    def _generate_runtime_primitive_recommendations(self):
        """Generate runtime primitive recommendations."""
        recommendations = []
        
        validation_results = self.report_data["runtime_primitive_validation"]
        
        if not validation_results["overall_passed"]:
            # SIGHTED_DEGRADED activation recommendations
            if not validation_results["sighted_degraded_activation"].get("passed", True):
                recommendations.append({
                    "priority": "CRITICAL",
                    "category": "Runtime Primitive",
                    "title": "SIGHTED_DEGRADED Activation Failed",
                    "description": "SIGHTED_DEGRADED mode activation test failed.",
                    "action": "Fix SIGHTED_DEGRADED activation issues before deployment."
                })
            
            # Domain priority system recommendations
            if not validation_results["domain_priority_system"].get("passed", True):
                recommendations.append({
                    "priority": "CRITICAL",
                    "category": "Runtime Primitive",
                    "title": "Domain Priority System Issues",
                    "description": "Domain priority system validation failed.",
                    "action": "Fix domain priority system issues before deployment."
                })
            
            # Conflict resolution recommendations
            if not validation_results["conflict_resolution"].get("passed", True):
                recommendations.append({
                    "priority": "HIGH",
                    "category": "Runtime Primitive",
                    "title": "Conflict Resolution Issues",
                    "description": "Conflict resolution validation failed.",
                    "action": "Fix conflict resolution issues before deployment."
                })
            
            # Fault injection recommendations
            if not validation_results["fault_injection"].get("passed", True):
                recommendations.append({
                    "priority": "HIGH",
                    "category": "Runtime Primitive",
                    "title": "Fault Injection Test Failures",
                    "description": "Fault injection tests failed.",
                    "action": "Fix fault injection test issues before deployment."
                })
        
        self.report_data["recommendations"].extend(recommendations)
    
    def _generate_compliance_recommendations(self):
        """Generate compliance recommendations."""
        recommendations = []
        
        compliance_results = self.report_data["compliance_status"]
        
        if not compliance_results["overall_compliant"]:
            # SOX compliance recommendations
            if not compliance_results["sox_compliance"].get("compliant", True):
                recommendations.append({
                    "priority": "CRITICAL",
                    "category": "Compliance",
                    "title": "SOX Compliance Issues",
                    "description": "SOX compliance validation failed.",
                    "action": "Address SOX compliance issues before deployment."
                })
            
            # Audit trail recommendations
            if not compliance_results["audit_trail"].get("compliant", True):
                recommendations.append({
                    "priority": "HIGH",
                    "category": "Compliance",
                    "title": "Audit Trail Issues",
                    "description": "Audit trail validation failed.",
                    "action": "Fix audit trail issues before deployment."
                })
            
            # Access control recommendations
            if not compliance_results["access_control"].get("compliant", True):
                recommendations.append({
                    "priority": "HIGH",
                    "category": "Compliance",
                    "title": "Access Control Issues",
                    "description": "Access control validation failed.",
                    "action": "Fix access control issues before deployment."
                })
        
        self.report_data["recommendations"].extend(recommendations)
    
    def calculate_overall_status(self) -> str:
        """Calculate overall deployment status."""
        security_passed = self.report_data["security_scan_results"].get("overall_passed", False)
        tests_passed = self.report_data["test_results"].get("overall_passed", False)
        runtime_passed = self.report_data["runtime_primitive_validation"].get("overall_passed", False)
        compliance_passed = self.report_data["compliance_status"].get("overall_compliant", False)
        
        if all([security_passed, tests_passed, runtime_passed, compliance_passed]):
            return "PASSED"
        elif any([not security_passed, not runtime_passed, not compliance_passed]):
            return "FAILED"
        else:
            return "WARNING"
    
    def generate_html_report(self) -> str:
        """Generate HTML deployment report."""
        status = self.calculate_overall_status()
        status_color = {
            "PASSED": "green",
            "FAILED": "red", 
            "WARNING": "orange"
        }.get(status, "gray")
        
        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MERID Deployment Report - {self.version}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid #eee;
        }}
        .status {{
            font-size: 24px;
            font-weight: bold;
            color: {status_color};
            padding: 10px 20px;
            border-radius: 5px;
            display: inline-block;
            margin-bottom: 10px;
        }}
        .section {{
            margin-bottom: 30px;
        }}
        .section h2 {{
            color: #333;
            border-bottom: 1px solid #ddd;
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
        }}
        .metric-value {{
            font-weight: bold;
        }}
        .recommendation {{
            background: #f8f9fa;
            border-left: 4px solid #007bff;
            padding: 15px;
            margin-bottom: 10px;
            border-radius: 4px;
        }}
        .recommendation.critical {{
            border-left-color: #dc3545;
        }}
        .recommendation.high {{
            border-left-color: #fd7e14;
        }}
        .recommendation.medium {{
            border-left-color: #ffc107;
        }}
        .priority {{
            font-weight: bold;
            text-transform: uppercase;
            font-size: 12px;
        }}
        .passed {{
            color: #28a745;
        }}
        .failed {{
            color: #dc3545;
        }}
        .warning {{
            color: #ffc107;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>MERID Deployment Report</h1>
            <div class="status">{status}</div>
            <p>Version: {self.version}</p>
            <p>Environment: {self.report_data['deployment_info']['environment']}</p>
            <p>Timestamp: {self.report_data['deployment_info']['timestamp']}</p>
            <p>Pipeline: <a href="{self.report_data['deployment_info']['pipeline_url']}">View Pipeline</a></p>
        </div>
        
        <div class="section">
            <h2>Security Scan Results</h2>
            <div class="metric">
                <span class="metric-label">Overall Status:</span>
                <span class="metric-value {'passed' if self.report_data['security_scan_results']['overall_passed'] else 'failed'}">
                    {'PASSED' if self.report_data['security_scan_results']['overall_passed'] else 'FAILED'}
                </span>
            </div>
            <div class="metric">
                <span class="metric-label">Trivy:</span>
                <span class="metric-value">
                    {self.report_data['security_scan_results']['trivy']['critical_count']} Critical, 
                    {self.report_data['security_scan_results']['trivy']['high_count']} High
                </span>
            </div>
            <div class="metric">
                <span class="metric-label">Snyk:</span>
                <span class="metric-value">
                    {self.report_data['security_scan_results']['snyk']['critical_count']} Critical, 
                    {self.report_data['security_scan_results']['snyk']['high_count']} High
                </span>
            </div>
            <div class="metric">
                <span class="metric-label">CodeQL:</span>
                <span class="metric-value">
                    {self.report_data['security_scan_results']['codeql']['critical_count']} Critical, 
                    {self.report_data['security_scan_results']['codeql']['high_count']} High
                </span>
            </div>
            <div class="metric">
                <span class="metric-label">Secrets:</span>
                <span class="metric-value">
                    {self.report_data['security_scan_results']['secrets']['critical_count']} Critical, 
                    {self.report_data['security_scan_results']['secrets']['high_count']} High
                </span>
            </div>
        </div>
        
        <div class="section">
            <h2>Test Results</h2>
            <div class="metric">
                <span class="metric-label">Overall Status:</span>
                <span class="metric-value {'passed' if self.report_data['test_results']['overall_passed'] else 'failed'}">
                    {'PASSED' if self.report_data['test_results']['overall_passed'] else 'FAILED'}
                </span>
            </div>
            <div class="metric">
                <span class="metric-label">Unit Tests:</span>
                <span class="metric-value">
                    {self.report_data['test_results']['unit_tests']['passed']}/{self.report_data['test_results']['unit_tests']['total']} 
                    ({self.report_data['test_results']['unit_tests']['coverage']:.1f}% coverage)
                </span>
            </div>
            <div class="metric">
                <span class="metric-label">Integration Tests:</span>
                <span class="metric-value">
                    {self.report_data['test_results']['integration_tests']['passed']}/{self.report_data['test_results']['integration_tests']['total']}
                </span>
            </div>
            <div class="metric">
                <span class="metric-label">E2E Tests:</span>
                <span class="metric-value">
                    {self.report_data['test_results']['e2e_tests']['passed']}/{self.report_data['test_results']['e2e_tests']['total']}
                </span>
            </div>
        </div>
        
        <div class="section">
            <h2>Runtime Primitive Validation</h2>
            <div class="metric">
                <span class="metric-label">Overall Status:</span>
                <span class="metric-value {'passed' if self.report_data['runtime_primitive_validation']['overall_passed'] else 'failed'}">
                    {'PASSED' if self.report_data['runtime_primitive_validation']['overall_passed'] else 'FAILED'}
                </span>
            </div>
            <div class="metric">
                <span class="metric-label">SIGHTED_DEGRADED Activation:</span>
                <span class="metric-value {'passed' if self.report_data['runtime_primitive_validation']['sighted_degraded_activation'].get('passed', True) else 'failed'}">
                    {'PASSED' if self.report_data['runtime_primitive_validation']['sighted_degraded_activation'].get('passed', True) else 'FAILED'}
                </span>
            </div>
            <div class="metric">
                <span class="metric-label">Domain Priority System:</span>
                <span class="metric-value {'passed' if self.report_data['runtime_primitive_validation']['domain_priority_system'].get('passed', True) else 'failed'}">
                    {'PASSED' if self.report_data['runtime_primitive_validation']['domain_priority_system'].get('passed', True) else 'FAILED'}
                </span>
            </div>
            <div class="metric">
                <span class="metric-label">Conflict Resolution:</span>
                <span class="metric-value {'passed' if self.report_data['runtime_primitive_validation']['conflict_resolution'].get('passed', True) else 'failed'}">
                    {'PASSED' if self.report_data['runtime_primitive_validation']['conflict_resolution'].get('passed', True) else 'FAILED'}
                </span>
            </div>
            <div class="metric">
                <span class="metric-label">Fault Injection:</span>
                <span class="metric-value {'passed' if self.report_data['runtime_primitive_validation']['fault_injection'].get('passed', True) else 'failed'}">
                    {'PASSED' if self.report_data['runtime_primitive_validation']['fault_injection'].get('passed', True) else 'FAILED'}
                </span>
            </div>
        </div>
        
        <div class="section">
            <h2>Compliance Status</h2>
            <div class="metric">
                <span class="metric-label">Overall Status:</span>
                <span class="metric-value {'passed' if self.report_data['compliance_status']['overall_compliant'] else 'failed'}">
                    {'COMPLIANT' if self.report_data['compliance_status']['overall_compliant'] else 'NON_COMPLIANT'}
                </span>
            </div>
            <div class="metric">
                <span class="metric-label">SOX Compliance:</span>
                <span class="metric-value {'passed' if self.report_data['compliance_status']['sox_compliance'].get('compliant', True) else 'failed'}">
                    {'COMPLIANT' if self.report_data['compliance_status']['sox_compliance'].get('compliant', True) else 'NON_COMPLIANT'}
                </span>
            </div>
            <div class="metric">
                <span class="metric-label">Audit Trail:</span>
                <span class="metric-value {'passed' if self.report_data['compliance_status']['audit_trail'].get('compliant', True) else 'failed'}">
                    {'COMPLIANT' if self.report_data['compliance_status']['audit_trail'].get('compliant', True) else 'NON_COMPLIANT'}
                </span>
            </div>
            <div class="metric">
                <span class="metric-label">Access Control:</span>
                <span class="metric-value {'passed' if self.report_data['compliance_status']['access_control'].get('compliant', True) else 'failed'}">
                    {'COMPLIANT' if self.report_data['compliance_status']['access_control'].get('compliant', True) else 'NON_COMPLIANT'}
                </span>
            </div>
        </div>
        
        <div class="section">
            <h2>Recommendations</h2>
            {self._generate_recommendations_html()}
        </div>
    </div>
</body>
</html>
        """
        return html
    
    def _generate_recommendations_html(self) -> str:
        """Generate HTML for recommendations."""
        html_parts = []
        
        for rec in self.report_data["recommendations"]:
            priority_class = rec["priority"].lower()
            html_parts.append(f"""
            <div class="recommendation {priority_class}">
                <div class="priority">{rec['priority']}</div>
                <div><strong>{rec['title']}</strong></div>
                <div>{rec['description']}</div>
                <div><strong>Action:</strong> {rec['action']}</div>
            </div>
            """)
        
        return "".join(html_parts)
    
    def save_report(self, filename: str):
        """Save report to file."""
        html_content = self.generate_html_report()
        
        with open(filename, 'w') as f:
            f.write(html_content)
        
        # Also save JSON data
        json_filename = filename.replace('.html', '.json')
        with open(json_filename, 'w') as f:
            json.dump(self.report_data, f, indent=2)
        
        print(f"Deployment report saved to {filename}")
        print(f"JSON data saved to {json_filename}")


def main():
    """Main entry point for deployment report generation."""
    parser = argparse.ArgumentParser(description='Generate MERID deployment report')
    parser.add_argument('--version', required=True, help='Deployment version')
    parser.add_argument('--pipeline-url', required=True, help='Pipeline URL')
    parser.add_argument('--output', default='deployment-report.html', help='Output filename')
    
    args = parser.parse_args()
    
    # Create report generator
    generator = DeploymentReportGenerator(args.version, args.pipeline_url)
    
    # Load security scan results (mock data for now)
    security_results = {
        "trivy": {"critical_count": 0, "high_count": 2, "scan_passed": True},
        "snyk": {"critical_count": 0, "high_count": 1, "scan_passed": True},
        "codeql": {"critical_count": 0, "high_count": 0, "scan_passed": True},
        "secrets": {"critical_count": 0, "high_count": 0, "scan_passed": True}
    }
    
    # Load test results (mock data for now)
    test_results = {
        "unit_tests": {"total": 150, "passed": 150, "failed": 0, "skipped": 0, "coverage": 92.5},
        "integration_tests": {"total": 45, "passed": 45, "failed": 0, "skipped": 0},
        "e2e_tests": {"total": 20, "passed": 20, "failed": 0, "skipped": 0}
    }
    
    # Load runtime primitive validation results (mock data for now)
    validation_results = {
        "sighted_degraded_activation": {"passed": True},
        "domain_priority_system": {"passed": True},
        "conflict_resolution": {"passed": True},
        "degraded_signal_handling": {"passed": True},
        "fault_injection": {"passed": True},
        "overall_passed": True
    }
    
    # Load compliance results (mock data for now)
    compliance_results = {
        "sox_compliance": {"compliant": True},
        "audit_trail": {"compliant": True},
        "access_control": {"compliant": True},
        "overall_compliant": True
    }
    
    # Add all results to report
    generator.add_security_scan_results(**security_results)
    generator.add_test_results(**test_results)
    generator.add_runtime_primitive_validation(validation_results)
    generator.add_compliance_status(compliance_results)
    
    # Save report
    generator.save_report(args.output)


if __name__ == "__main__":
    main()
