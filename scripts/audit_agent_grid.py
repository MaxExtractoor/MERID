#!/usr/bin/env python3
"""
Agent Grid Audit Script

Scans the codebase for:
1. Agents not declared in the grid (agent_grid_config.yaml)
2. Hardcoded MAX_* constants that should be config-driven
3. Missing correlation IDs in agent-to-agent calls
4. Lane violations (dev agents in production paths)

Usage:
    python scripts/audit_agent_grid.py [--fix] [--verbose]
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Whitelisted constants (documented in audit)
WHITELISTED_CONSTANTS = {
    "_MIN_CUTOFF_MINUTES",  # Kalshi protocol minimum
    "MAX_CONCURRENT_REQUESTS",  # HTTP pool sizing
    "MAX_ORDERS_PER_CYCLE",  # Rate limiting (cosmetic)
}

# Acceptable lane patterns
PRODUCTION_LANES = {"signal", "risk", "execution", "analytics"}
DEV_LANES = {"dev", "test", "observer"}


@dataclass
class AuditFinding:
    """Single audit finding."""
    file: str
    line: int
    category: str  # 'missing_grid_entry', 'hardcoded_max', 'lane_violation', 'missing_trace'
    message: str
    severity: str  # 'error', 'warning', 'info'
    suggestion: str = ""


@dataclass
class AuditReport:
    """Complete audit results."""
    findings: List[AuditFinding] = field(default_factory=list)
    agents_in_grid: Set[str] = field(default_factory=set)
    agents_in_code: Set[str] = field(default_factory=set)
    hardcoded_constants: List[Tuple[str, int, str]] = field(default_factory=list)

    @property
    def errors(self) -> List[AuditFinding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> List[AuditFinding]:
        return [f for f in self.findings if f.severity == "warning"]

    def summary(self) -> str:
        return (
            f"Audit Summary:\n"
            f"  Agents in grid: {len(self.agents_in_grid)}\n"
            f"  Agents found in code: {len(self.agents_in_code)}\n"
            f"  Errors: {len(self.errors)}\n"
            f"  Warnings: {len(self.warnings)}\n"
            f"  Hardcoded constants: {len(self.hardcoded_constants)}\n"
        )


def scan_grid_entries(config_path: str = "config/kalshi_agent_grid.yaml") -> Set[str]:
    """Extract agent IDs from grid config."""
    agents = set()
    path = Path(config_path)
    if not path.exists():
        # Try relative to project root
        path = Path(__file__).parent.parent / config_path
    
    if not path.exists():
        print(f"Warning: Grid config not found at {config_path}")
        return agents

    try:
        import yaml
        with open(path, 'r') as f:
            config = yaml.safe_load(f)
        
        for agent in config.get("agents", []):
            agent_id = agent.get("agent_id") or f"kalshi-{agent['name']}"
            agents.add(agent_id)
    except Exception as e:
        print(f"Warning: Could not parse grid config: {e}")

    return agents


def find_hardcoded_constants(file_path: Path) -> List[Tuple[int, str, str]]:
    """Find MAX_* constants in a Python file."""
    findings = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
    except Exception:
        return findings

    # Pattern: MAX_SOMETHING = value (at module/class level)
    max_pattern = re.compile(r'^\s*(MAX_\w+)\s*=\s*(\d+)')
    
    for i, line in enumerate(lines, 1):
        match = max_pattern.match(line)
        if match:
            const_name = match.group(1)
            if const_name not in WHITELISTED_CONSTANTS:
                findings.append((i, const_name, line.strip()))

    return findings


def find_agent_classes(file_path: Path) -> List[Tuple[int, str]]:
    """Find agent class definitions."""
    findings = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read())
    except SyntaxError:
        return findings

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Check if it's an agent class
            if any(
                base.attr in ("Agent", "TradingAgent", "BaseAgent") 
                for base in node.bases 
                if isinstance(base, ast.Attribute)
            ) or "Agent" in node.name:
                findings.append((node.lineno, node.name))

    return findings


def find_cross_lane_calls(file_path: Path) -> List[Tuple[int, str]]:
    """Find potential cross-lane violations (simplified heuristic)."""
    findings = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
    except Exception:
        return findings

    # Patterns that might indicate cross-lane calls
    suspicious_patterns = [
        (r'\.(submit_order|execute_trade|place_order)\s*\(', "Direct execution call"),
        (r'OrderRouter', "OrderRouter import (should use ExecutionGuard)"),
        (r'dev_swarm|DevSwarm', "DevSwarm reference in non-dev file"),
        (r'mock_data|MockData', "Mock data in non-test file"),
    ]

    for i, line in enumerate(lines, 1):
        for pattern, message in suspicious_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                # Skip test files
                if "test" in str(file_path).lower():
                    continue
                findings.append((i, message))

    return findings


def find_missing_traces(file_path: Path) -> List[Tuple[int, str]]:
    """Find async methods without trace/correlation ID handling."""
    findings = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
    except Exception:
        return findings

    # Look for async def that might need tracing
    async_pattern = re.compile(r'^\s*async def (get_opinion|submit_to_consensus|execute_signal)')
    
    for i, line in enumerate(lines, 1):
        if async_pattern.search(line):
            # Check if the next few lines have trace/correlation
            context = '\n'.join(lines[i:i+10])
            if 'trace_id' not in context and 'correlation_id' not in context:
                findings.append((i, f"Method {line.strip()} may need trace_id/correlation_id"))

    return findings


def scan_directory(directory: Path, report: AuditReport) -> None:
    """Recursively scan directory for audit issues."""
    
    for file_path in directory.rglob("*.py"):
        # Skip tests and legacy
        if any(x in str(file_path) for x in ["__pycache__", "_legacy", "tests/", "test_"]):
            continue

        rel_path = str(file_path.relative_to(directory.parent if directory.name == "merid" else directory))

        # Find hardcoded constants
        for line, const_name, line_content in find_hardcoded_constants(file_path):
            report.hardcoded_constants.append((rel_path, line, const_name))
            report.findings.append(AuditFinding(
                file=rel_path,
                line=line,
                category="hardcoded_max",
                message=f"Hardcoded constant: {const_name}",
                severity="warning",
                suggestion=f"Move to settings with bankroll-derived default"
            ))

        # Find agent classes
        for line, class_name in find_agent_classes(file_path):
            agent_id = f"kalshi-{class_name.lower().replace('agent', '')}"
            report.agents_in_code.add(agent_id)

        # Find cross-lane issues
        for line, message in find_cross_lane_calls(file_path):
            report.findings.append(AuditFinding(
                file=rel_path,
                line=line,
                category="lane_violation",
                message=message,
                severity="error" if "submit_order" in message else "warning",
                suggestion="Route through proper gateway"
            ))

        # Find missing traces
        for line, message in find_missing_traces(file_path):
            report.findings.append(AuditFinding(
                file=rel_path,
                line=line,
                category="missing_trace",
                message=message,
                severity="warning",
                suggestion="Add trace_id and correlation_id propagation"
            ))


def main():
    parser = argparse.ArgumentParser(description="Audit agent grid and swarm matrix")
    parser.add_argument("--fix", action="store_true", help="Attempt auto-fixes (not yet implemented)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")
    args = parser.parse_args()

    # Find project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    merid_dir = project_root / "merid"

    report = AuditReport()

    # Scan grid config
    print("Scanning grid config...")
    report.agents_in_grid = scan_grid_entries(str(project_root / "config" / "kalshi_agent_grid.yaml"))

    # Scan codebase
    print("Scanning codebase for agents and constants...")
    if merid_dir.exists():
        scan_directory(merid_dir, report)
    else:
        # Try project root
        scan_directory(project_root, report)

    # Check for agents in code but not in grid
    for agent_id in report.agents_in_code:
        if agent_id not in report.agents_in_grid:
            report.findings.append(AuditFinding(
                file="grid",
                line=0,
                category="missing_grid_entry",
                message=f"Agent {agent_id} found in code but not in grid config",
                severity="error",
                suggestion=f"Add {agent_id} to config/kalshi_agent_grid.yaml"
            ))

    # Output results
    print("\n" + "=" * 60)
    print(report.summary())
    print("=" * 60)

    if report.errors:
        print("\nERRORS (block live trading):")
        for finding in report.errors:
            print(f"  {finding.file}:{finding.line} [{finding.category}]")
            print(f"    {finding.message}")
            if finding.suggestion:
                print(f"    Suggestion: {finding.suggestion}")

    if report.warnings:
        print("\nWARNINGS (should fix):")
        for finding in report.warnings[:20]:  # Limit output
            print(f"  {finding.file}:{finding.line} [{finding.category}] {finding.message}")
        if len(report.warnings) > 20:
            print(f"  ... and {len(report.warnings) - 20} more warnings")

    # Exit code
    sys.exit(len(report.errors))


if __name__ == "__main__":
    main()
