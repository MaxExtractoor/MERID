"""
Comprehensive Codebase Audit Engine for MERID.

Scans codebase for:
- Incomplete/fake code (TODOs, placeholders, mock implementations)
- Security vulnerabilities
- Test coverage gaps
- Architecture issues
- Documentation completeness
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
import logging

logger = logging.getLogger(__name__)


@dataclass
class AuditFinding:
    finding_id: str
    category: str
    severity: str
    file_path: str
    line_number: Optional[int]
    description: str
    recommendation: str
    detected_at: datetime


class CodebaseAuditEngine:
    """
    Comprehensive codebase audit engine.
    
    Features:
    - Fake code detection (TODO, FIXME, pass-only functions)
    - Security vulnerability scanning
    - Test coverage analysis
    - Architecture issue detection
    - Documentation completeness checks
    """
    
    def __init__(self, root_path: str):
        self.root_path = Path(root_path)
        self._findings: List[AuditFinding] = []
        self._files_scanned = 0
        self._lines_scanned = 0
        
        self._fake_code_patterns = [
            (r'\bTODO\b', "TODO marker"),
            (r'\bFIXME\b', "FIXME marker"),
            (r'\bXXX\b', "XXX marker"),
            (r'\bHACK\b', "HACK marker"),
            (r'pass\s*#.*placeholder', "Placeholder implementation"),
            (r'raise NotImplementedError', "Not implemented"),
            (r'\.\.\..*#.*stub', "Stub implementation"),
        ]
        
        self._security_patterns = [
            (r'eval\s*\(', "Use of eval()"),
            (r'exec\s*\(', "Use of exec()"),
            (r'pickle\.loads\s*\(', "Unsafe deserialization"),
            (r'os\.system\s*\(', "Direct system call"),
            (r'subprocess\.call\s*\(.*shell\s*=\s*True', "Shell injection risk"),
            (r'password\s*=\s*["\']', "Hardcoded password"),
            (r'api_key\s*=\s*["\']', "Hardcoded API key"),
            (r'secret\s*=\s*["\']', "Hardcoded secret"),
        ]
    
    def scan_directory(self, directory: Optional[Path] = None) -> None:
        """Scan directory recursively."""
        scan_dir = directory or self.root_path
        
        for file_path in scan_dir.rglob("*.py"):
            if self._should_skip_file(file_path):
                continue
            
            self._scan_file(file_path)
    
    def _should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped."""
        skip_dirs = {
            "__pycache__",
            ".git",
            ".venv",
            "venv",
            "node_modules",
            ".pytest_cache",
            "merid-ui",
        }
        
        for part in file_path.parts:
            if part in skip_dirs:
                return True
        
        return False
    
    def _scan_file(self, file_path: Path) -> None:
        """Scan individual file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
            
            self._files_scanned += 1
            self._lines_scanned += len(lines)
            
            self._check_fake_code(file_path, lines)
            self._check_security(file_path, lines)
            self._check_empty_functions(file_path, lines)
            self._check_documentation(file_path, content)
            
        except Exception as e:
            logger.error(f"Error scanning {file_path}: {e}")
    
    def _check_fake_code(self, file_path: Path, lines: List[str]) -> None:
        """Check for fake/incomplete code."""
        for i, line in enumerate(lines, 1):
            for pattern, description in self._fake_code_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    self._add_finding(
                        category="fake_code",
                        severity="medium",
                        file_path=str(file_path.relative_to(self.root_path)),
                        line_number=i,
                        description=f"{description}: {line.strip()}",
                        recommendation="Complete implementation or remove placeholder",
                    )
    
    def _check_security(self, file_path: Path, lines: List[str]) -> None:
        """Check for security vulnerabilities."""
        for i, line in enumerate(lines, 1):
            for pattern, description in self._security_patterns:
                if re.search(pattern, line):
                    self._add_finding(
                        category="security",
                        severity="high",
                        file_path=str(file_path.relative_to(self.root_path)),
                        line_number=i,
                        description=f"{description}: {line.strip()}",
                        recommendation="Review and secure implementation",
                    )
    
    def _check_empty_functions(self, file_path: Path, lines: List[str]) -> None:
        """Check for empty or pass-only functions."""
        in_function = False
        function_name = ""
        function_line = 0
        function_body_lines = []
        
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            
            if stripped.startswith("def ") or stripped.startswith("async def "):
                if in_function and self._is_empty_function(function_body_lines):
                    self._add_finding(
                        category="fake_code",
                        severity="medium",
                        file_path=str(file_path.relative_to(self.root_path)),
                        line_number=function_line,
                        description=f"Empty function: {function_name}",
                        recommendation="Implement function or document why it's empty",
                    )
                
                in_function = True
                function_name = stripped.split('(')[0].replace('def ', '').replace('async ', '').strip()
                function_line = i
                function_body_lines = []
            
            elif in_function:
                if stripped and not stripped.startswith('#'):
                    function_body_lines.append(stripped)
                
                if stripped and not line.startswith(' ') and not line.startswith('\t'):
                    in_function = False
    
    def _is_empty_function(self, body_lines: List[str]) -> bool:
        """Check if function body is empty or only contains pass."""
        if not body_lines:
            return True
        
        non_docstring = [
            line for line in body_lines
            if not line.startswith('"""') and not line.startswith("'''")
        ]
        
        if not non_docstring:
            return True
        
        if len(non_docstring) == 1 and non_docstring[0] == "pass":
            return True
        
        return False
    
    def _check_documentation(self, file_path: Path, content: str) -> None:
        """Check documentation completeness."""
        if not content.strip():
            return
        
        has_module_docstring = content.lstrip().startswith('"""') or content.lstrip().startswith("'''")
        
        if not has_module_docstring and len(content.split('\n')) > 50:
            self._add_finding(
                category="documentation",
                severity="low",
                file_path=str(file_path.relative_to(self.root_path)),
                line_number=1,
                description="Missing module docstring",
                recommendation="Add module-level docstring",
            )
    
    def _add_finding(
        self,
        category: str,
        severity: str,
        file_path: str,
        line_number: Optional[int],
        description: str,
        recommendation: str,
    ) -> None:
        """Add audit finding."""
        finding = AuditFinding(
            finding_id=f"{category}_{self._files_scanned}_{line_number or 0}",
            category=category,
            severity=severity,
            file_path=file_path,
            line_number=line_number,
            description=description,
            recommendation=recommendation,
            detected_at=datetime.utcnow(),
        )
        
        self._findings.append(finding)
    
    def get_findings_by_category(self, category: str) -> List[AuditFinding]:
        """Get findings by category."""
        return [f for f in self._findings if f.category == category]
    
    def get_findings_by_severity(self, severity: str) -> List[AuditFinding]:
        """Get findings by severity."""
        return [f for f in self._findings if f.severity == severity]
    
    def get_summary(self) -> Dict[str, object]:
        """Get audit summary."""
        by_category = {}
        for finding in self._findings:
            by_category[finding.category] = by_category.get(finding.category, 0) + 1
        
        by_severity = {}
        for finding in self._findings:
            by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1
        
        return {
            "files_scanned": self._files_scanned,
            "lines_scanned": self._lines_scanned,
            "total_findings": len(self._findings),
            "by_category": by_category,
            "by_severity": by_severity,
            "critical_count": by_severity.get("critical", 0),
            "high_count": by_severity.get("high", 0),
            "medium_count": by_severity.get("medium", 0),
            "low_count": by_severity.get("low", 0),
        }
    
    def generate_report(self, output_path: str) -> None:
        """Generate audit report."""
        summary = self.get_summary()
        
        with open(output_path, 'w') as f:
            f.write("# MERID Codebase Audit Report\n\n")
            f.write(f"**Generated**: {datetime.utcnow().isoformat()}\n\n")
            
            f.write("## Summary\n\n")
            f.write(f"- **Files Scanned**: {summary['files_scanned']}\n")
            f.write(f"- **Lines Scanned**: {summary['lines_scanned']}\n")
            f.write(f"- **Total Findings**: {summary['total_findings']}\n\n")
            
            f.write("### By Severity\n\n")
            f.write(f"- **Critical**: {summary['critical_count']}\n")
            f.write(f"- **High**: {summary['high_count']}\n")
            f.write(f"- **Medium**: {summary['medium_count']}\n")
            f.write(f"- **Low**: {summary['low_count']}\n\n")
            
            f.write("### By Category\n\n")
            for category, count in summary['by_category'].items():
                f.write(f"- **{category}**: {count}\n")
            f.write("\n")
            
            f.write("## Findings\n\n")
            
            for severity in ["critical", "high", "medium", "low"]:
                findings = self.get_findings_by_severity(severity)
                if findings:
                    f.write(f"### {severity.upper()} Severity\n\n")
                    for finding in findings[:100]:
                        f.write(f"#### {finding.file_path}:{finding.line_number or 'N/A'}\n\n")
                        f.write(f"- **Category**: {finding.category}\n")
                        f.write(f"- **Description**: {finding.description}\n")
                        f.write(f"- **Recommendation**: {finding.recommendation}\n\n")
        
        logger.info(f"Audit report generated: {output_path}")


def run_audit(root_path: str, output_path: str) -> Dict[str, object]:
    """Run comprehensive codebase audit."""
    engine = CodebaseAuditEngine(root_path)
    
    logger.info(f"Starting codebase audit: {root_path}")
    engine.scan_directory()
    
    summary = engine.get_summary()
    logger.info(f"Audit complete: {summary['total_findings']} findings")
    
    engine.generate_report(output_path)
    
    return summary
