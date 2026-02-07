"""
MERID Swarm QA & Release Orchestrator

Unified orchestrator that sequences all QA roles for every major change:
1. Code Realism Auditor
2. Configuration Drift Auditor
3. Skipped-Task Detector
4. Production Readiness Gatekeeper
5. Release Readiness Engineer

Ensures no skipped tasks, no fake code, no drift, and full production readiness.
"""

import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
import re

logger = logging.getLogger(__name__)


class Severity(Enum):
    """Finding severity levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingCategory(Enum):
    """Categories of findings."""
    PSEUDO_CODE = "pseudo_code"
    PLACEHOLDER = "placeholder"
    MOCK_CODE = "mock_code"
    TODO_FIXME = "todo_fixme"
    MISSING_TEST = "missing_test"
    MISSING_DOC = "missing_doc"
    SECURITY_GAP = "security_gap"
    CONFIG_DRIFT = "config_drift"
    INFRA_DRIFT = "infra_drift"
    SKIPPED_TASK = "skipped_task"
    INCOMPLETE_IMPL = "incomplete_impl"


class Verdict(Enum):
    """Final verdict options."""
    APPROVED = "approved"
    BLOCKED = "blocked"
    INCOMPLETE = "incomplete"
    CONDITIONAL = "conditional"


@dataclass
class Finding:
    """A single QA finding."""
    finding_id: str
    category: FindingCategory
    severity: Severity
    title: str
    description: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    code_snippet: Optional[str] = None
    remediation: str = ""
    is_blocker: bool = False
    detected_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ChecklistItem:
    """A checklist item with status."""
    item_id: str
    section: str
    description: str
    is_complete: bool = False
    is_applicable: bool = True
    notes: str = ""
    findings: List[Finding] = field(default_factory=list)


@dataclass
class RoleResult:
    """Result from a QA role execution."""
    role_name: str
    passed: bool
    findings: List[Finding] = field(default_factory=list)
    checklist_items: List[ChecklistItem] = field(default_factory=list)
    summary: str = ""
    executed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class OrchestratorResult:
    """Final orchestrator result."""
    change_id: str
    change_title: str
    verdict: Verdict
    role_results: List[RoleResult] = field(default_factory=list)
    all_findings: List[Finding] = field(default_factory=list)
    blockers: List[Finding] = field(default_factory=list)
    summary: str = ""
    executed_at: datetime = field(default_factory=datetime.utcnow)


class CodeRealismAuditor:
    """
    Role 4: Code Realism Auditor
    
    Audits code for pseudo-code, placeholders, and incomplete implementations.
    """
    
    PSEUDO_CODE_PATTERNS = [
        (r'\.\.\.', 'Ellipsis placeholder'),
        (r'#\s*TODO', 'TODO comment'),
        (r'//\s*TODO', 'TODO comment'),
        (r'#\s*FIXME', 'FIXME comment'),
        (r'//\s*FIXME', 'FIXME comment'),
        (r'pass\s*#', 'Pass with comment (likely placeholder)'),
        (r'raise\s+NotImplementedError', 'NotImplementedError'),
        (r'return\s+None\s*#.*implement', 'Placeholder return'),
        (r'#\s*STUB', 'Stub marker'),
        (r'//\s*STUB', 'Stub marker'),
    ]
    
    MOCK_PATTERNS = [
        (r'mock_', 'Mock prefix in production code'),
        (r'fake_', 'Fake prefix in production code'),
        (r'dummy_', 'Dummy prefix in production code'),
        (r'sample_', 'Sample prefix in production code'),
        (r'test_data\s*=', 'Test data in production'),
        (r'hardcoded.*secret', 'Hardcoded secret'),
        (r'api_key\s*=\s*["\'][^"\']+["\']', 'Hardcoded API key'),
    ]
    
    def __init__(self):
        self.findings: List[Finding] = []
    
    def audit_file(self, file_path: str, content: str, is_test_file: bool = False) -> List[Finding]:
        """Audit a single file for pseudo-code and placeholders."""
        findings = []
        lines = content.split('\n')
        
        for line_num, line in enumerate(lines, 1):
            # Skip if test file (mocks are acceptable)
            if is_test_file:
                continue
            
            # Check pseudo-code patterns
            for pattern, description in self.PSEUDO_CODE_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    finding = Finding(
                        finding_id=f"pseudo_{file_path}_{line_num}",
                        category=FindingCategory.PSEUDO_CODE,
                        severity=Severity.HIGH,
                        title=f"Pseudo-code detected: {description}",
                        description=f"Found '{description}' in production code",
                        file_path=file_path,
                        line_number=line_num,
                        code_snippet=line.strip()[:100],
                        remediation=f"Replace placeholder with real implementation",
                        is_blocker=True,
                    )
                    findings.append(finding)
            
            # Check mock patterns (only in non-test files)
            for pattern, description in self.MOCK_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    finding = Finding(
                        finding_id=f"mock_{file_path}_{line_num}",
                        category=FindingCategory.MOCK_CODE,
                        severity=Severity.CRITICAL,
                        title=f"Mock/fake code detected: {description}",
                        description=f"Found '{description}' in production code",
                        file_path=file_path,
                        line_number=line_num,
                        code_snippet=line.strip()[:100],
                        remediation=f"Remove mock code or move to test file",
                        is_blocker=True,
                    )
                    findings.append(finding)
        
        return findings
    
    def execute(self, files: Dict[str, str]) -> RoleResult:
        """Execute the Code Realism Auditor role."""
        all_findings = []
        
        for file_path, content in files.items():
            is_test = 'test' in file_path.lower() or file_path.startswith('tests/')
            findings = self.audit_file(file_path, content, is_test)
            all_findings.extend(findings)
        
        passed = not any(f.is_blocker for f in all_findings)
        
        return RoleResult(
            role_name="Code Realism Auditor",
            passed=passed,
            findings=all_findings,
            summary=f"Audited {len(files)} files, found {len(all_findings)} issues ({sum(1 for f in all_findings if f.is_blocker)} blockers)",
        )


class ConfigDriftAuditor:
    """
    Role 2: Configuration Drift Auditor
    
    Detects configuration drift between baseline and current state.
    """
    
    def __init__(self):
        self.findings: List[Finding] = []
    
    def compare_configs(
        self,
        baseline: Dict[str, Any],
        current: Dict[str, Any],
        config_name: str,
    ) -> List[Finding]:
        """Compare baseline config against current config."""
        findings = []
        
        # Find keys in baseline but not in current
        for key in baseline:
            if key not in current:
                findings.append(Finding(
                    finding_id=f"drift_missing_{config_name}_{key}",
                    category=FindingCategory.CONFIG_DRIFT,
                    severity=Severity.HIGH,
                    title=f"Missing config key: {key}",
                    description=f"Key '{key}' exists in baseline but not in current config",
                    remediation=f"Add '{key}' to current config or remove from baseline",
                    is_blocker=True,
                ))
            elif baseline[key] != current[key]:
                findings.append(Finding(
                    finding_id=f"drift_changed_{config_name}_{key}",
                    category=FindingCategory.CONFIG_DRIFT,
                    severity=Severity.MEDIUM,
                    title=f"Config value changed: {key}",
                    description=f"Key '{key}' has different value: baseline={baseline[key]}, current={current[key]}",
                    remediation=f"Verify change is intentional and documented",
                    is_blocker=False,
                ))
        
        # Find keys in current but not in baseline
        for key in current:
            if key not in baseline:
                findings.append(Finding(
                    finding_id=f"drift_new_{config_name}_{key}",
                    category=FindingCategory.CONFIG_DRIFT,
                    severity=Severity.LOW,
                    title=f"New config key: {key}",
                    description=f"Key '{key}' exists in current but not in baseline",
                    remediation=f"Add '{key}' to baseline or remove from current",
                    is_blocker=False,
                ))
        
        return findings
    
    def check_environment_parity(
        self,
        dev_config: Dict[str, Any],
        staging_config: Dict[str, Any],
        prod_config: Dict[str, Any],
    ) -> List[Finding]:
        """Check for environment parity issues."""
        findings = []
        
        # Get all keys across environments
        all_keys = set(dev_config.keys()) | set(staging_config.keys()) | set(prod_config.keys())
        
        for key in all_keys:
            envs_with_key = []
            if key in dev_config:
                envs_with_key.append('dev')
            if key in staging_config:
                envs_with_key.append('staging')
            if key in prod_config:
                envs_with_key.append('prod')
            
            if len(envs_with_key) < 3:
                missing_envs = {'dev', 'staging', 'prod'} - set(envs_with_key)
                findings.append(Finding(
                    finding_id=f"parity_{key}",
                    category=FindingCategory.CONFIG_DRIFT,
                    severity=Severity.HIGH,
                    title=f"Environment parity issue: {key}",
                    description=f"Key '{key}' missing in environments: {missing_envs}",
                    remediation=f"Add '{key}' to all environments or document why it differs",
                    is_blocker=True,
                ))
        
        return findings
    
    def execute(
        self,
        baseline_configs: Dict[str, Dict[str, Any]],
        current_configs: Dict[str, Dict[str, Any]],
    ) -> RoleResult:
        """Execute the Configuration Drift Auditor role."""
        all_findings = []
        
        for config_name in baseline_configs:
            if config_name in current_configs:
                findings = self.compare_configs(
                    baseline_configs[config_name],
                    current_configs[config_name],
                    config_name,
                )
                all_findings.extend(findings)
        
        passed = not any(f.is_blocker for f in all_findings)
        
        return RoleResult(
            role_name="Configuration Drift Auditor",
            passed=passed,
            findings=all_findings,
            summary=f"Compared {len(baseline_configs)} configs, found {len(all_findings)} drift issues",
        )


class SkippedTaskDetector:
    """
    Role 5: Skipped-Task Detector
    
    Detects skipped or forgotten tasks before release.
    """
    
    def __init__(self):
        self.checklist_items: List[ChecklistItem] = []
    
    def generate_checklist(self, release_scope: Dict[str, Any]) -> List[ChecklistItem]:
        """Generate checklist for detecting skipped tasks."""
        items = []
        
        # PR verification
        items.append(ChecklistItem(
            item_id="pr_merged",
            section="Code",
            description="All PRs for this release are merged",
        ))
        items.append(ChecklistItem(
            item_id="pr_reviewed",
            section="Code",
            description="All PRs have at least one approval",
        ))
        
        # Ticket verification
        items.append(ChecklistItem(
            item_id="tickets_linked",
            section="Tracking",
            description="All tickets have linked PRs",
        ))
        items.append(ChecklistItem(
            item_id="tickets_tested",
            section="Tracking",
            description="All tickets have test evidence",
        ))
        items.append(ChecklistItem(
            item_id="tickets_documented",
            section="Tracking",
            description="All tickets have documentation updates",
        ))
        
        # Config/Infra verification
        items.append(ChecklistItem(
            item_id="config_iac",
            section="Infrastructure",
            description="Config changes reflected in IaC",
        ))
        items.append(ChecklistItem(
            item_id="config_envs",
            section="Infrastructure",
            description="Config changes applied to all environments",
        ))
        
        # Security verification
        items.append(ChecklistItem(
            item_id="security_review",
            section="Security",
            description="Security review completed for new features",
        ))
        items.append(ChecklistItem(
            item_id="secrets_rotated",
            section="Security",
            description="No secrets exposed or needing rotation",
        ))
        
        # Test verification
        items.append(ChecklistItem(
            item_id="tests_pass",
            section="Testing",
            description="All automated tests pass",
        ))
        items.append(ChecklistItem(
            item_id="tests_coverage",
            section="Testing",
            description="Test coverage meets threshold",
        ))
        
        return items
    
    def calculate_risk_score(self, items: List[ChecklistItem]) -> str:
        """Calculate skipped-task risk score."""
        incomplete = sum(1 for item in items if not item.is_complete and item.is_applicable)
        total = sum(1 for item in items if item.is_applicable)
        
        if total == 0:
            return "UNKNOWN"
        
        ratio = incomplete / total
        
        if ratio == 0:
            return "LOW"
        elif ratio < 0.1:
            return "LOW"
        elif ratio < 0.25:
            return "MEDIUM"
        elif ratio < 0.5:
            return "HIGH"
        else:
            return "CRITICAL"
    
    def execute(self, release_scope: Dict[str, Any]) -> RoleResult:
        """Execute the Skipped-Task Detector role."""
        items = self.generate_checklist(release_scope)
        
        # Mark items based on release scope (in real implementation, would check actual state)
        findings = []
        for item in items:
            if not item.is_complete:
                findings.append(Finding(
                    finding_id=f"skipped_{item.item_id}",
                    category=FindingCategory.SKIPPED_TASK,
                    severity=Severity.HIGH,
                    title=f"Potentially skipped task: {item.description}",
                    description=f"Checklist item '{item.item_id}' not verified",
                    remediation=f"Verify: {item.description}",
                    is_blocker=True,
                ))
        
        risk_score = self.calculate_risk_score(items)
        passed = risk_score in ["LOW"]
        
        return RoleResult(
            role_name="Skipped-Task Detector",
            passed=passed,
            findings=findings,
            checklist_items=items,
            summary=f"Skipped-Task Risk Score: {risk_score} ({len(findings)} items need verification)",
        )


class ProductionReadinessGatekeeper:
    """
    Role 3: Production Readiness Gatekeeper
    
    Verifies production readiness and no mock code remains.
    """
    
    def __init__(self):
        self.checklist_items: List[ChecklistItem] = []
    
    def generate_checklist(self) -> List[ChecklistItem]:
        """Generate production readiness checklist."""
        items = []
        
        # Code Quality
        items.append(ChecklistItem(
            item_id="code_compiles",
            section="Code Quality",
            description="Code compiles without errors",
        ))
        items.append(ChecklistItem(
            item_id="tests_pass",
            section="Code Quality",
            description="All tests pass",
        ))
        items.append(ChecklistItem(
            item_id="static_analysis",
            section="Code Quality",
            description="Static analysis yields no critical issues",
        ))
        items.append(ChecklistItem(
            item_id="no_debug_flags",
            section="Code Quality",
            description="No debug flags enabled in production",
        ))
        
        # Observability
        items.append(ChecklistItem(
            item_id="metrics_exist",
            section="Observability",
            description="Metrics exist for critical paths",
        ))
        items.append(ChecklistItem(
            item_id="logs_exist",
            section="Observability",
            description="Logs exist for errors and critical paths",
        ))
        items.append(ChecklistItem(
            item_id="health_checks",
            section="Observability",
            description="Health checks exist for services",
        ))
        
        # Security
        items.append(ChecklistItem(
            item_id="input_validation",
            section="Security",
            description="Input validation verified",
        ))
        items.append(ChecklistItem(
            item_id="authz_verified",
            section="Security",
            description="Authorization flows verified",
        ))
        items.append(ChecklistItem(
            item_id="secrets_secure",
            section="Security",
            description="Secrets handled securely",
        ))
        
        # Deployment
        items.append(ChecklistItem(
            item_id="rollback_plan",
            section="Deployment",
            description="Rollback plan documented",
        ))
        items.append(ChecklistItem(
            item_id="feature_flags",
            section="Deployment",
            description="Feature flags in place for risky changes",
        ))
        
        return items
    
    def execute(
        self,
        code_audit_result: RoleResult,
        drift_audit_result: RoleResult,
    ) -> RoleResult:
        """Execute the Production Readiness Gatekeeper role."""
        items = self.generate_checklist()
        findings = []
        
        # Incorporate findings from other roles
        for finding in code_audit_result.findings:
            if finding.is_blocker:
                findings.append(finding)
        
        for finding in drift_audit_result.findings:
            if finding.is_blocker:
                findings.append(finding)
        
        # Check for incomplete checklist items
        for item in items:
            if not item.is_complete and item.is_applicable:
                findings.append(Finding(
                    finding_id=f"readiness_{item.item_id}",
                    category=FindingCategory.INCOMPLETE_IMPL,
                    severity=Severity.HIGH,
                    title=f"Readiness check incomplete: {item.description}",
                    description=f"Production readiness item '{item.item_id}' not verified",
                    remediation=f"Verify: {item.description}",
                    is_blocker=True,
                ))
        
        passed = not any(f.is_blocker for f in findings)
        verdict = "GO" if passed else "NO-GO"
        
        return RoleResult(
            role_name="Production Readiness Gatekeeper",
            passed=passed,
            findings=findings,
            checklist_items=items,
            summary=f"Verdict: {verdict} ({len([f for f in findings if f.is_blocker])} blockers)",
        )


class ReleaseReadinessEngineer:
    """
    Role 1: Release Readiness Engineer
    
    Generates complete software release checklist.
    """
    
    def __init__(self):
        self.checklist_items: List[ChecklistItem] = []
    
    def generate_full_checklist(self) -> List[ChecklistItem]:
        """Generate complete release checklist."""
        items = []
        
        # Requirements & Design
        items.append(ChecklistItem(
            item_id="req_signoff",
            section="Requirements & Design",
            description="Requirements signed off by stakeholders",
        ))
        items.append(ChecklistItem(
            item_id="design_review",
            section="Requirements & Design",
            description="Design review completed",
        ))
        
        # Code Implementation
        items.append(ChecklistItem(
            item_id="code_complete",
            section="Code Implementation",
            description="All planned features implemented",
        ))
        items.append(ChecklistItem(
            item_id="code_reviewed",
            section="Code Implementation",
            description="All code reviewed and approved",
        ))
        items.append(ChecklistItem(
            item_id="no_todos",
            section="Code Implementation",
            description="No TODO/FIXME in production code",
        ))
        
        # Testing
        items.append(ChecklistItem(
            item_id="unit_tests",
            section="Testing",
            description="Unit tests pass with >80% coverage",
        ))
        items.append(ChecklistItem(
            item_id="integration_tests",
            section="Testing",
            description="Integration tests pass",
        ))
        items.append(ChecklistItem(
            item_id="e2e_tests",
            section="Testing",
            description="E2E tests pass",
        ))
        items.append(ChecklistItem(
            item_id="performance_tests",
            section="Testing",
            description="Performance tests meet SLAs",
        ))
        items.append(ChecklistItem(
            item_id="security_tests",
            section="Testing",
            description="Security tests pass",
        ))
        
        # Smart Contracts
        items.append(ChecklistItem(
            item_id="contract_tests",
            section="Smart Contracts",
            description="Contract tests pass locally",
        ))
        items.append(ChecklistItem(
            item_id="testnet_deploy",
            section="Smart Contracts",
            description="Contracts deployed and verified on testnet",
        ))
        items.append(ChecklistItem(
            item_id="audit_status",
            section="Smart Contracts",
            description="Audit completed or scheduled for critical contracts",
        ))
        
        # Config & Infrastructure
        items.append(ChecklistItem(
            item_id="iac_updated",
            section="Config & Infrastructure",
            description="IaC updated and applied",
        ))
        items.append(ChecklistItem(
            item_id="env_parity",
            section="Config & Infrastructure",
            description="Environment parity verified",
        ))
        items.append(ChecklistItem(
            item_id="secrets_configured",
            section="Config & Infrastructure",
            description="Secrets configured in secret manager",
        ))
        items.append(ChecklistItem(
            item_id="migrations_ready",
            section="Config & Infrastructure",
            description="Database migrations ready and tested",
        ))
        
        # Observability
        items.append(ChecklistItem(
            item_id="dashboards_ready",
            section="Observability",
            description="Monitoring dashboards ready",
        ))
        items.append(ChecklistItem(
            item_id="alerts_configured",
            section="Observability",
            description="Alerts configured for critical paths",
        ))
        items.append(ChecklistItem(
            item_id="logs_structured",
            section="Observability",
            description="Logs structured and queryable",
        ))
        
        # Security & Compliance
        items.append(ChecklistItem(
            item_id="threat_model",
            section="Security & Compliance",
            description="Threat model reviewed",
        ))
        items.append(ChecklistItem(
            item_id="access_controls",
            section="Security & Compliance",
            description="Access controls verified",
        ))
        items.append(ChecklistItem(
            item_id="compliance_check",
            section="Security & Compliance",
            description="Compliance requirements met",
        ))
        
        # Documentation
        items.append(ChecklistItem(
            item_id="user_docs",
            section="Documentation",
            description="User documentation updated",
        ))
        items.append(ChecklistItem(
            item_id="ops_runbook",
            section="Documentation",
            description="Operations runbook updated",
        ))
        items.append(ChecklistItem(
            item_id="incident_runbook",
            section="Documentation",
            description="Incident response runbook updated",
        ))
        
        # Release Plan
        items.append(ChecklistItem(
            item_id="version_tagged",
            section="Release Plan",
            description="Version tagged in repository",
        ))
        items.append(ChecklistItem(
            item_id="rollout_strategy",
            section="Release Plan",
            description="Rollout strategy defined (canary, blue-green, etc.)",
        ))
        items.append(ChecklistItem(
            item_id="rollback_tested",
            section="Release Plan",
            description="Rollback procedure tested",
        ))
        
        return items
    
    def execute(self, all_role_results: List[RoleResult]) -> RoleResult:
        """Execute the Release Readiness Engineer role."""
        items = self.generate_full_checklist()
        findings = []
        
        # Aggregate findings from all roles
        for role_result in all_role_results:
            for finding in role_result.findings:
                if finding.is_blocker:
                    findings.append(finding)
        
        # Check for incomplete checklist items
        for item in items:
            if not item.is_complete and item.is_applicable:
                findings.append(Finding(
                    finding_id=f"release_{item.item_id}",
                    category=FindingCategory.SKIPPED_TASK,
                    severity=Severity.HIGH,
                    title=f"Release checklist incomplete: {item.description}",
                    description=f"Release item '{item.item_id}' not verified",
                    remediation=f"Verify: {item.description}",
                    is_blocker=True,
                ))
        
        passed = not any(f.is_blocker for f in findings)
        
        return RoleResult(
            role_name="Release Readiness Engineer",
            passed=passed,
            findings=findings,
            checklist_items=items,
            summary=f"Release {'APPROVED' if passed else 'BLOCKED'} ({len([f for f in findings if f.is_blocker])} blockers)",
        )


class SwarmQAReleaseOrchestrator:
    """
    MERID Swarm QA & Release Orchestrator
    
    Sequences all QA roles for every major change:
    1. Code Realism Auditor
    2. Configuration Drift Auditor
    3. Skipped-Task Detector
    4. Production Readiness Gatekeeper
    5. Release Readiness Engineer
    """
    
    def __init__(self):
        self.code_auditor = CodeRealismAuditor()
        self.drift_auditor = ConfigDriftAuditor()
        self.skipped_detector = SkippedTaskDetector()
        self.readiness_gatekeeper = ProductionReadinessGatekeeper()
        self.release_engineer = ReleaseReadinessEngineer()
    
    def execute(
        self,
        change_id: str,
        change_title: str,
        files: Dict[str, str],
        baseline_configs: Dict[str, Dict[str, Any]],
        current_configs: Dict[str, Dict[str, Any]],
        release_scope: Dict[str, Any],
    ) -> OrchestratorResult:
        """
        Execute the full QA orchestration sequence.
        
        Args:
            change_id: Unique identifier for the change
            change_title: Human-readable title
            files: Dict of file_path -> content for code audit
            baseline_configs: Baseline configuration state
            current_configs: Current configuration state
            release_scope: Release scope information
        
        Returns:
            OrchestratorResult with final verdict and all findings
        """
        logger.info(f"Starting QA orchestration for change '{change_id}'")
        
        role_results = []
        all_findings = []
        
        # Step 1: Code Realism Auditor
        logger.info("Executing Role 4: Code Realism Auditor")
        code_result = self.code_auditor.execute(files)
        role_results.append(code_result)
        all_findings.extend(code_result.findings)
        
        # Step 2: Configuration Drift Auditor
        logger.info("Executing Role 2: Configuration Drift Auditor")
        drift_result = self.drift_auditor.execute(baseline_configs, current_configs)
        role_results.append(drift_result)
        all_findings.extend(drift_result.findings)
        
        # Step 3: Skipped-Task Detector
        logger.info("Executing Role 5: Skipped-Task Detector")
        skipped_result = self.skipped_detector.execute(release_scope)
        role_results.append(skipped_result)
        all_findings.extend(skipped_result.findings)
        
        # Step 4: Production Readiness Gatekeeper
        logger.info("Executing Role 3: Production Readiness Gatekeeper")
        readiness_result = self.readiness_gatekeeper.execute(code_result, drift_result)
        role_results.append(readiness_result)
        all_findings.extend(readiness_result.findings)
        
        # Step 5: Release Readiness Engineer
        logger.info("Executing Role 1: Release Readiness Engineer")
        release_result = self.release_engineer.execute(role_results)
        role_results.append(release_result)
        all_findings.extend(release_result.findings)
        
        # Determine final verdict
        blockers = [f for f in all_findings if f.is_blocker]
        
        if not blockers:
            verdict = Verdict.APPROVED
        elif any(f.severity == Severity.CRITICAL for f in blockers):
            verdict = Verdict.BLOCKED
        else:
            verdict = Verdict.INCOMPLETE
        
        # Generate summary
        summary_lines = [
            f"Change: {change_title} ({change_id})",
            f"Verdict: {verdict.value.upper()}",
            f"Total Findings: {len(all_findings)}",
            f"Blockers: {len(blockers)}",
            "",
            "Role Results:",
        ]
        
        for result in role_results:
            status = "✓ PASS" if result.passed else "✗ FAIL"
            summary_lines.append(f"  {status} {result.role_name}: {result.summary}")
        
        if blockers:
            summary_lines.append("")
            summary_lines.append("Blockers:")
            for blocker in blockers:
                summary_lines.append(f"  - [{blocker.severity.value.upper()}] {blocker.title}")
        
        summary = "\n".join(summary_lines)
        
        logger.info(f"QA orchestration complete: {verdict.value}")
        
        return OrchestratorResult(
            change_id=change_id,
            change_title=change_title,
            verdict=verdict,
            role_results=role_results,
            all_findings=all_findings,
            blockers=blockers,
            summary=summary,
        )
    
    def generate_report(self, result: OrchestratorResult) -> str:
        """Generate a detailed report from orchestrator result."""
        lines = [
            "=" * 80,
            "MERID QA & RELEASE ORCHESTRATOR REPORT",
            "=" * 80,
            "",
            f"Change ID: {result.change_id}",
            f"Change Title: {result.change_title}",
            f"Executed At: {result.executed_at.isoformat()}",
            "",
            "-" * 80,
            f"VERDICT: {result.verdict.value.upper()}",
            "-" * 80,
            "",
        ]
        
        # Role results
        lines.append("ROLE RESULTS:")
        lines.append("")
        
        for role_result in result.role_results:
            status = "✓ PASS" if role_result.passed else "✗ FAIL"
            lines.append(f"  {status} {role_result.role_name}")
            lines.append(f"      {role_result.summary}")
            lines.append("")
        
        # Blockers
        if result.blockers:
            lines.append("-" * 80)
            lines.append("BLOCKERS (Must be resolved before release):")
            lines.append("-" * 80)
            lines.append("")
            
            for blocker in result.blockers:
                lines.append(f"  [{blocker.severity.value.upper()}] {blocker.title}")
                lines.append(f"      Category: {blocker.category.value}")
                if blocker.file_path:
                    lines.append(f"      File: {blocker.file_path}:{blocker.line_number or ''}")
                lines.append(f"      Description: {blocker.description}")
                lines.append(f"      Remediation: {blocker.remediation}")
                lines.append("")
        
        # All findings
        lines.append("-" * 80)
        lines.append(f"ALL FINDINGS ({len(result.all_findings)} total):")
        lines.append("-" * 80)
        lines.append("")
        
        for finding in result.all_findings:
            blocker_marker = "[BLOCKER] " if finding.is_blocker else ""
            lines.append(f"  {blocker_marker}[{finding.severity.value.upper()}] {finding.title}")
        
        lines.append("")
        lines.append("=" * 80)
        lines.append("END OF REPORT")
        lines.append("=" * 80)
        
        return "\n".join(lines)


_orchestrator: Optional[SwarmQAReleaseOrchestrator] = None


def get_qa_release_orchestrator() -> SwarmQAReleaseOrchestrator:
    """Get global SwarmQAReleaseOrchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = SwarmQAReleaseOrchestrator()
    return _orchestrator
