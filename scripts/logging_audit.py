#!/usr/bin/env python3
"""
MERID Production Stack Logging Audit Script

This script systematically analyzes the production stack's logging to expose:
1. Inconsistent logging patterns
2. Missing context in log messages
3. Silent failures
4. Poor explainability
5. Diagnostic noise
6. Mixed logging approaches
7. Lack of structured logging
8. Missing correlation IDs
9. Print statement pollution
10. Risk-critical areas with insufficient logging

Usage:
    python scripts/logging_audit.py
"""

import ast
import os
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class LoggingIssue:
    """Represents a logging issue found in the codebase."""
    file_path: str
    line_number: int
    issue_type: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    description: str
    code_snippet: str
    recommendation: str


@dataclass
class FileAnalysis:
    """Analysis results for a single file."""
    file_path: str
    total_log_calls: int = 0
    logger_calls: Dict[str, int] = field(default_factory=dict)  # info, warning, error, debug, exception
    print_statements: int = 0
    structured_logs: int = 0
    unstructured_logs: int = 0
    issues: List[LoggingIssue] = field(default_factory=list)
    has_get_logger: bool = False
    has_logging_getlogger: bool = False
    has_context_in_logs: int = 0  # logs with asset, order_id, ticker, etc.


class LoggingAuditor:
    """Audits logging patterns across the MERID production stack."""
    
    def __init__(self, root_path: str = "c:\\Dev\\MERID"):
        self.root_path = Path(root_path)
        self.issues: List[LoggingIssue] = []
        self.file_analyses: Dict[str, FileAnalysis] = {}
        
        # Production stack paths to audit
        self.production_paths = [
            "web/main_15m_lean.py",
            "merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
            "merid/risk/profiles/crypto_15m_profile.py",
            "merid/prediction/unified_sizing.py",
            "merid/prediction/agent_grid_15m.py",
            "merid/event_venues/kalshi/",
            "merid/risk/",
            "merid/prediction/",
            "data/unified_spot_service.py",
            "merid/loop_15m/",
        ]
        
        # Context keywords that indicate good logging
        self.context_keywords = [
            'asset', 'ticker', 'order_id', 'market_id', 'agent_id',
            'notional', 'price', 'bankroll', 'exposure', 'risk',
            'position', 'contract', 'side', 'reason', 'error'
        ]
        
        # Risk-critical patterns that require robust logging
        self.risk_critical_patterns = [
            'window_tracking', 'exposure', 'halt', 'stop_loss',
            'position_close', 'order_reject', 'risk_limit',
            'drawdown', 'circuit_breaker', 'kill_switch'
        ]
    
    def audit(self) -> Dict:
        """Run the full logging audit."""
        print("=" * 80)
        print("MERID PRODUCTION STACK LOGGING AUDIT")
        print("=" * 80)
        
        # Analyze production files
        for path_pattern in self.production_paths:
            if path_pattern.endswith('/'):
                # Directory pattern
                search_path = self.root_path / path_pattern
                if search_path.exists():
                    for py_file in search_path.rglob("*.py"):
                        self._analyze_file(py_file)
            else:
                # File pattern
                file_path = self.root_path / path_pattern
                if file_path.exists():
                    self._analyze_file(file_path)
        
        # Generate report
        report = self._generate_report()
        self._print_report(report)
        
        return report
    
    def _analyze_file(self, file_path: Path):
        """Analyze a single Python file for logging issues."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
        except Exception as e:
            print(f"Failed to read {file_path}: {e}")
            return
        
        analysis = FileAnalysis(file_path=str(file_path))
        
        # Parse AST
        try:
            tree = ast.parse(content)
        except SyntaxError:
            print(f"Syntax error in {file_path}")
            return
        
        # Check for logger imports
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == 'utils.logger' and any(alias.name == 'get_logger' for alias in node.names):
                    analysis.has_get_logger = True
                elif node.module == 'logging' and any(alias.name == 'getLogger' for alias in node.names):
                    analysis.has_logging_getlogger = True
        
        # Analyze each line
        for i, line in enumerate(lines, 1):
            self._analyze_line(line, i, analysis, lines)
        
        self.file_analyses[str(file_path)] = analysis
        self.issues.extend(analysis.issues)
    
    def _analyze_line(self, line: str, line_num: int, analysis: FileAnalysis, all_lines: List[str]):
        """Analyze a single line for logging patterns."""
        
        # Check for print statements
        if 'print(' in line and not line.strip().startswith('#'):
            analysis.print_statements += 1
            severity = "HIGH" if "stderr" not in line else "MEDIUM"
            analysis.issues.append(LoggingIssue(
                file_path=analysis.file_path,
                line_number=line_num,
                issue_type="PRINT_STATEMENT",
                severity=severity,
                description="Print statement found instead of proper logging",
                code_snippet=line.strip(),
                recommendation="Replace print() with logger.info/debug/error for proper log management"
            ))
        
        # Check for logger calls
        logger_match = re.search(r'logger\.(info|warning|error|debug|exception)\(', line)
        if logger_match:
            log_level = logger_match.group(1)
            analysis.total_log_calls += 1
            analysis.logger_calls[log_level] = analysis.logger_calls.get(log_level, 0) + 1
            
            # Check if structured (key-value pairs)
            if '=' in line and ('%s' in line or '%d' in line or '{' in line):
                analysis.structured_logs += 1
            else:
                analysis.unstructured_logs += 1
            
            # Check for context keywords
            has_context = any(keyword in line.lower() for keyword in self.context_keywords)
            if has_context:
                analysis.has_context_in_logs += 1
            
            # Check for risk-critical patterns
            is_risk_critical = any(pattern in line.lower() for pattern in self.risk_critical_patterns)
            
            # Check for missing context in risk-critical logs
            if is_risk_critical and not has_context:
                analysis.issues.append(LoggingIssue(
                    file_path=analysis.file_path,
                    line_number=line_num,
                    issue_type="MISSING_CONTEXT",
                    severity="HIGH",
                    description=f"Risk-critical log missing context (contains: {logger_match.group(1)})",
                    code_snippet=line.strip(),
                    recommendation="Add context: asset, order_id, notional, exposure, or reason to explain the risk event"
                ))
            
            # Check for generic error messages
            if log_level in ['error', 'exception']:
                if 'failed' in line.lower() or 'error' in line.lower():
                    if not any(keyword in line.lower() for keyword in ['reason', 'because', 'due to', 'caused by']):
                        analysis.issues.append(LoggingIssue(
                            file_path=analysis.file_path,
                            line_number=line_num,
                            issue_type="POOR_EXPLAINABILITY",
                            severity="MEDIUM",
                            description="Error log lacks explainability (no reason/causal context)",
                            code_snippet=line.strip(),
                            recommendation="Add causal context: 'failed because X', 'error due to Y', or 'caused by Z'"
                        ))
        
        # Check for silent exception handling
        if 'except' in line and 'pass' in all_lines[min(line_num, len(all_lines)-1)]:
            analysis.issues.append(LoggingIssue(
                file_path=analysis.file_path,
                line_number=line_num,
                issue_type="SILENT_FAILURE",
                severity="CRITICAL",
                description="Silent exception handling (except: pass)",
                code_snippet=line.strip(),
                recommendation="Add logging to the except block to capture and analyze failures"
            ))
        
        # Check for diagnostic noise
        if 'DIAGNOSTIC' in line or 'CRITICAL DIAGNOSTIC' in line:
            analysis.issues.append(LoggingIssue(
                file_path=analysis.file_path,
                line_number=line_num,
                issue_type="DIAGNOSTIC_NOISE",
                severity="LOW",
                description="Diagnostic marker polluting production logs",
                code_snippet=line.strip(),
                recommendation="Remove diagnostic markers or use a separate debug log level"
            ))
    
    def _generate_report(self) -> Dict:
        """Generate a comprehensive audit report."""
        total_files = len(self.file_analyses)
        total_log_calls = sum(analysis.total_log_calls for analysis in self.file_analyses.values())
        total_print_statements = sum(analysis.print_statements for analysis in self.file_analyses.values())
        total_issues = len(self.issues)
        
        # Categorize issues
        issues_by_type = defaultdict(list)
        issues_by_severity = defaultdict(list)
        issues_by_file = defaultdict(list)
        
        for issue in self.issues:
            issues_by_type[issue.issue_type].append(issue)
            issues_by_severity[issue.severity].append(issue)
            issues_by_file[issue.file_path].append(issue)
        
        # Calculate structured vs unstructured
        total_structured = sum(analysis.structured_logs for analysis in self.file_analyses.values())
        total_unstructured = sum(analysis.unstructured_logs for analysis in self.file_analyses.values())
        
        return {
            "summary": {
                "total_files_analyzed": total_files,
                "total_log_calls": total_log_calls,
                "total_print_statements": total_print_statements,
                "total_issues": total_issues,
                "structured_logs": total_structured,
                "unstructured_logs": total_unstructured,
                "structured_percentage": (total_structured / (total_structured + total_unstructured) * 100) if (total_structured + total_unstructured) > 0 else 0,
            },
            "issues_by_type": {k: len(v) for k, v in issues_by_type.items()},
            "issues_by_severity": {k: len(v) for k, v in issues_by_severity.items()},
            "issues_by_file": {k: len(v) for k, v in issues_by_file.items()},
            "file_analyses": self.file_analyses,
            "all_issues": self.issues,
        }
    
    def _print_report(self, report: Dict):
        """Print the audit report."""
        print("\n" + "=" * 80)
        print("AUDIT SUMMARY")
        print("=" * 80)
        
        summary = report["summary"]
        print(f"Files analyzed: {summary['total_files_analyzed']}")
        print(f"Total log calls: {summary['total_log_calls']}")
        print(f"Total print statements: {summary['total_print_statements']}")
        print(f"Total issues found: {summary['total_issues']}")
        print(f"Structured logs: {summary['structured_logs']} ({summary['structured_percentage']:.1f}%)")
        print(f"Unstructured logs: {summary['unstructured_logs']} ({100 - summary['structured_percentage']:.1f}%)")
        
        print("\n" + "=" * 80)
        print("ISSUES BY SEVERITY")
        print("=" * 80)
        for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            count = report["issues_by_severity"].get(severity, 0)
            if count > 0:
                print(f"{severity}: {count}")
        
        print("\n" + "=" * 80)
        print("ISSUES BY TYPE")
        print("=" * 80)
        for issue_type, count in sorted(report["issues_by_type"].items(), key=lambda x: x[1], reverse=True):
            print(f"{issue_type}: {count}")
        
        print("\n" + "=" * 80)
        print("TOP 10 FILES WITH MOST ISSUES")
        print("=" * 80)
        sorted_files = sorted(report["issues_by_file"].items(), key=lambda x: x[1], reverse=True)[:10]
        for file_path, count in sorted_files:
            print(f"{file_path}: {count} issues")
        
        print("\n" + "=" * 80)
        print("CRITICAL ISSUES (REQUIRE IMMEDIATE ATTENTION)")
        print("=" * 80)
        critical_issues = [issue for issue in report["all_issues"] if issue.severity == "CRITICAL"]
        for issue in critical_issues[:20]:  # Show first 20
            print(f"\n{issue.file_path}:{issue.line_number}")
            print(f"  Type: {issue.issue_type}")
            print(f"  Code: {issue.code_snippet}")
            print(f"  Recommendation: {issue.recommendation}")
        
        print("\n" + "=" * 80)
        print("HIGH SEVERITY ISSUES")
        print("=" * 80)
        high_issues = [issue for issue in report["all_issues"] if issue.severity == "HIGH"]
        for issue in high_issues[:20]:  # Show first 20
            print(f"\n{issue.file_path}:{issue.line_number}")
            print(f"  Type: {issue.issue_type}")
            print(f"  Code: {issue.code_snippet}")
            print(f"  Recommendation: {issue.recommendation}")
        
        print("\n" + "=" * 80)
        print("RECOMMENDATIONS FOR ROBUST LOGGING")
        print("=" * 80)
        print("""
1. STANDARDIZE LOGGING APPROACH
   - Use get_logger() from utils.logger consistently
   - Remove all print() statements
   - Define clear log level usage policy

2. ADD STRUCTURED LOGGING
   - Use key-value pairs: logger.info("action", key=value)
   - Include correlation IDs for transaction tracing
   - Add timestamps, user IDs, session IDs

3. IMPROVE CONTEXT IN RISK-CRITICAL LOGS
   - Always include: asset, order_id, notional, exposure
   - Explain WHY risk decisions were made
   - Log risk parameter values at decision points

4. ENHANCE ERROR EXPLAINABILITY
   - Add causal context: "failed because X"
   - Include stack traces for exceptions
   - Log recovery actions taken

5. REMOVE DIAGNOSTIC NOISE
   - Remove CRITICAL DIAGNOSTIC markers
   - Use separate debug log level for diagnostics
   - Implement log filtering in production

6. IMPLEMENT CORRELATION IDS
   - Generate unique ID per transaction
   - Pass correlation ID through call stack
   - Log correlation ID in every related message

7. ADD BUSINESS CONTEXT
   - Log business impact of events
   - Include user-facing error messages
   - Track SLA compliance metrics

8. IMPLEMENT LOG AGGREGATION
   - Centralize log collection
   - Add log search and filtering
   - Implement alerting on critical patterns
        """)
        
        # Save detailed report to file
        output_path = self.root_path / "output" / "logging_audit_report.md"
        output_path.parent.mkdir(exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("# MERID Production Stack Logging Audit Report\n\n")
            f.write(f"Generated: {os.popen('date /t && time /t').read()}\n\n")
            f.write("## Summary\n\n")
            f.write(f"- Files analyzed: {summary['total_files_analyzed']}\n")
            f.write(f"- Total log calls: {summary['total_log_calls']}\n")
            f.write(f"- Total print statements: {summary['total_print_statements']}\n")
            f.write(f"- Total issues found: {summary['total_issues']}\n")
            f.write(f"- Structured logs: {summary['structured_logs']} ({summary['structured_percentage']:.1f}%)\n")
            f.write(f"- Unstructured logs: {summary['unstructured_logs']} ({100 - summary['structured_percentage']:.1f}%)\n\n")
            
            f.write("## Issues by Severity\n\n")
            for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
                count = report["issues_by_severity"].get(severity, 0)
                if count > 0:
                    f.write(f"- {severity}: {count}\n")
            
            f.write("\n## Issues by Type\n\n")
            for issue_type, count in sorted(report["issues_by_type"].items(), key=lambda x: x[1], reverse=True):
                f.write(f"- {issue_type}: {count}\n")
            
            f.write("\n## All Issues\n\n")
            for issue in report["all_issues"]:
                f.write(f"### {issue.severity}: {issue.issue_type}\n")
                f.write(f"**File:** {issue.file_path}:{issue.line_number}\n")
                f.write(f"**Code:** `{issue.code_snippet}`\n")
                f.write(f"**Description:** {issue.description}\n")
                f.write(f"**Recommendation:** {issue.recommendation}\n\n")
        
        print(f"\nDetailed report saved to: {output_path}")


if __name__ == "__main__":
    auditor = LoggingAuditor()
    report = auditor.audit()
