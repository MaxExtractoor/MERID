#!/usr/bin/env python3
"""
Spread Threshold Alignment Audit Script

This script audits the spread threshold configuration across the MERID codebase
to ensure alignment with:
1. 10-75c canonical entry price range
2. Industry standards for prediction market liquidity (2026 research)
3. End-to-end consistency across upstream, midstream, and downstream components

Industry Research Findings (2026):
- Kalshi high-liquidity markets: 1-3¢ spreads
- Kalshi moderate-liquidity markets: 2-5¢ spreads  
- Kalshi lower-liquidity markets: 5-15¢ spreads
- Polymarket excellent liquidity: 0-1¢ (0-1.5%)
- Polymarket good liquidity: 1-2¢ (1.5-3%)
- Polymarket moderate liquidity: 2-4¢ (3-6%)
- Polymarket poor liquidity: 4+¢ (6%+)
- 15-minute crypto markets inherently wider due to short duration
- Recommended max spread for 15m crypto: 15-20c
- Recommended spread gate for momentum: 8-10c

Current Configuration Issues:
- universe.max_spread_cents: 100c (20-100x industry liquid thresholds)
- momentum_fvg.spread_gate_cents: 30c (3-6x industry good liquidity)
- guardrails.min_spread_gate_cents: 30c (3-6x industry good liquidity)
"""

import sys
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from collections import defaultdict

@dataclass
class SpreadThresholdIssue:
    """Represents a spread threshold alignment issue."""
    location: str
    component: str
    current_value: float
    recommended_value: float
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    reason: str
    file_path: str
    line_number: int

class SpreadThresholdAuditor:
    """Audits spread threshold configuration across the codebase."""
    
    def __init__(self, root_path: str = "c:\\Dev\\MERID"):
        self.root_path = Path(root_path)
        self.issues: List[SpreadThresholdIssue] = []
        
        # Industry-recommended thresholds (2026 research)
        self.recommended_max_spread = 20.0  # 20c for 15m crypto (accounting for inherent wider spreads)
        self.recommended_spread_gate = 10.0  # 10c for momentum entries
        self.recommended_min_spread_gate = 8.0  # 8c minimum quality filter
        
        # 10-75c canonical entry price range
        self.min_entry_cents = 10
        self.max_entry_cents = 75
        
    def audit_profile_yaml(self) -> None:
        """Audit the profile YAML configuration."""
        yaml_path = self.root_path / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        if not yaml_path.exists():
            self.issues.append(SpreadThresholdIssue(
                location="config/profiles/kalshi_crypto_15m_v2.yaml",
                component="profile_yaml",
                current_value=0,
                recommended_value=0,
                severity="CRITICAL",
                reason="Profile YAML file not found",
                file_path=str(yaml_path),
                line_number=0
            ))
            return
            
        content = yaml_path.read_text(encoding='utf-8')
        
        # Check universe.max_spread_cents
        universe_match = re.search(r'universe:.*?(?=\n[a-z_]+:|$)', content, re.DOTALL)
        if universe_match:
            universe_section = universe_match.group(0)
            max_spread_match = re.search(r'max_spread_cents:\s*(\d+)', universe_section)
            if max_spread_match:
                current_value = float(max_spread_match.group(1))
                if current_value > self.recommended_max_spread:
                    self.issues.append(SpreadThresholdIssue(
                        location="config/profiles/kalshi_crypto_15m_v2.yaml",
                        component="universe.max_spread_cents",
                        current_value=current_value,
                        recommended_value=self.recommended_max_spread,
                        severity="CRITICAL",
                        reason=f"Current {current_value}c is {current_value/self.recommended_max_spread:.1f}x industry recommendation. "
                               f"Allows trading in extremely illiquid markets. Industry: 15-20c for 15m crypto.",
                        file_path=str(yaml_path),
                        line_number=content[:universe_match.start() + max_spread_match.start()].count('\n') + 1
                    ))
        
        # Check momentum_fvg.spread_gate_cents
        momentum_match = re.search(r'momentum_fvg:.*?(?=\n[a-z_]+:|$)', content, re.DOTALL)
        if momentum_match:
            momentum_section = momentum_match.group(0)
            spread_gate_match = re.search(r'spread_gate_cents:\s*(\d+)', momentum_section)
            if spread_gate_match:
                current_value = float(spread_gate_match.group(1))
                if current_value > self.recommended_spread_gate:
                    self.issues.append(SpreadThresholdIssue(
                        location="config/profiles/kalshi_crypto_15m_v2.yaml",
                        component="momentum_fvg.spread_gate_cents",
                        current_value=current_value,
                        recommended_value=self.recommended_spread_gate,
                        severity="HIGH",
                        reason=f"Current {current_value}c is {current_value/self.recommended_spread_gate:.1f}x industry recommendation. "
                               f"Allows momentum entries in poor liquidity. Industry: 8-10c for quality filter.",
                        file_path=str(yaml_path),
                        line_number=content[:momentum_match.start() + spread_gate_match.start()].count('\n') + 1
                    ))
        
        # Check guardrails.min_spread_gate_cents (if present)
        guardrails_match = re.search(r'guardrails:.*?(?=\n[a-z_]+:|$)', content, re.DOTALL)
        if guardrails_match:
            guardrails_section = guardrails_match.group(0)
            min_spread_gate_match = re.search(r'min_spread_gate_cents:\s*(\d+)', guardrails_section)
            if min_spread_gate_match:
                current_value = float(min_spread_gate_match.group(1))
                if current_value > self.recommended_min_spread_gate:
                    self.issues.append(SpreadThresholdIssue(
                        location="config/profiles/kalshi_crypto_15m_v2.yaml",
                        component="guardrails.min_spread_gate_cents",
                        current_value=current_value,
                        recommended_value=self.recommended_min_spread_gate,
                        severity="HIGH",
                        reason=f"Current {current_value}c is {current_value/self.recommended_min_spread_gate:.1f}x industry recommendation. "
                               f"Quality filter too permissive. Industry: 8-10c for minimum quality.",
                        file_path=str(yaml_path),
                        line_number=content[:guardrails_match.start() + min_spread_gate_match.start()].count('\n') + 1
                    ))
    
    def audit_python_files(self) -> None:
        """Audit Python files for hardcoded spread thresholds."""
        
        # Files to audit
        files_to_audit = [
            "merid/prediction/agent_grid_15m.py",
            "merid/event_venues/kalshi/models.py",
            "merid/event_venues/kalshi/microstructure.py",
            "merid/event_venues/kalshi/dynamic_thresholds.py",
        ]
        
        for file_path in files_to_audit:
            full_path = self.root_path / file_path
            if not full_path.exists():
                continue
                
            content = full_path.read_text(encoding='utf-8')
            lines = content.split('\n')
            
            # Check for hardcoded spread thresholds
            for i, line in enumerate(lines, 1):
                # Check for spread threshold constants
                if 'SPREAD_THRESHOLD' in line or 'WIDE_SPREAD' in line:
                    match = re.search(r'=\s*(\d+)', line)
                    if match:
                        value = float(match.group(1))
                        if value > self.recommended_max_spread:
                            self.issues.append(SpreadThresholdIssue(
                                location=file_path,
                                component="hardcoded_spread_threshold",
                                current_value=value,
                                recommended_value=self.recommended_max_spread,
                                severity="MEDIUM",
                                reason=f"Hardcoded threshold {value}c exceeds recommendation {self.recommended_max_spread}c",
                                file_path=str(full_path),
                                line_number=i
                            ))
    
    def audit_test_files(self) -> None:
        """Audit test files for outdated spread threshold assertions."""
        
        test_dir = self.root_path / "tests"
        if not test_dir.exists():
            return
            
        # Find test files with spread references
        for test_file in test_dir.rglob("*.py"):
            content = test_file.read_text(encoding='utf-8')
            lines = content.split('\n')
            
            for i, line in enumerate(lines, 1):
                # Check for assertions expecting 100c spread
                if 'max_spread_cents' in line and ('100' in line or 'assert' in line):
                    if '100' in line and '==' in line:
                        self.issues.append(SpreadThresholdIssue(
                            location=str(test_file.relative_to(self.root_path)),
                            component="test_assertion",
                            current_value=100.0,
                            recommended_value=self.recommended_max_spread,
                            severity="MEDIUM",
                            reason="Test asserts 100c max_spread_cents, should be updated to 20c",
                            file_path=str(test_file),
                            line_number=i
                        ))
    
    def check_entry_price_alignment(self) -> None:
        """Check if spread thresholds align with 10-75c entry price range."""
        
        # Spread should be a reasonable percentage of entry price
        # For 10c entry, 20c spread = 200% (too high)
        # For 75c entry, 20c spread = 27% (reasonable)
        # For 42c entry (midpoint), 20c spread = 48% (borderline)
        
        midpoint_entry = (self.min_entry_cents + self.max_entry_cents) / 2
        spread_as_pct = (self.recommended_max_spread / midpoint_entry) * 100
        
        if spread_as_pct > 50:
            self.issues.append(SpreadThresholdIssue(
                location="entry_price_alignment",
                component="spread_vs_entry_price",
                current_value=spread_as_pct,
                recommended_value=50.0,
                severity="HIGH",
                reason=f"Spread {self.recommended_max_spread}c is {spread_as_pct:.1f}% of midpoint entry {midpoint_entry}c. "
                       f"Should be <= 50% to avoid excessive friction. Consider reducing to 15c.",
                file_path="N/A",
                line_number=0
            ))
    
    def generate_report(self) -> str:
        """Generate a comprehensive audit report."""
        
        report = []
        report.append("=" * 80)
        report.append("SPREAD THRESHOLD ALIGNMENT AUDIT REPORT")
        report.append("=" * 80)
        report.append(f"Root Path: {self.root_path}")
        report.append(f"Total Issues Found: {len(self.issues)}")
        report.append("")
        
        # Group by severity
        by_severity = defaultdict(list)
        for issue in self.issues:
            by_severity[issue.severity].append(issue)
        
        for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            if severity in by_severity:
                report.append(f"\n{severity} ISSUES ({len(by_severity[severity])}):")
                report.append("-" * 80)
                for issue in by_severity[severity]:
                    report.append(f"  Location: {issue.location}")
                    report.append(f"  Component: {issue.component}")
                    report.append(f"  Current: {issue.current_value}c")
                    report.append(f"  Recommended: {issue.recommended_value}c")
                    report.append(f"  Reason: {issue.reason}")
                    if issue.file_path != "N/A":
                        report.append(f"  File: {issue.file_path}:{issue.line_number}")
                    report.append("")
        
        # Summary statistics
        report.append("\n" + "=" * 80)
        report.append("SUMMARY STATISTICS")
        report.append("=" * 80)
        report.append(f"CRITICAL: {len(by_severity.get('CRITICAL', []))}")
        report.append(f"HIGH: {len(by_severity.get('HIGH', []))}")
        report.append(f"MEDIUM: {len(by_severity.get('MEDIUM', []))}")
        report.append(f"LOW: {len(by_severity.get('LOW', []))}")
        report.append("")
        
        # Recommendations
        report.append("\n" + "=" * 80)
        report.append("RECOMMENDED ACTIONS")
        report.append("=" * 80)
        report.append("1. Update config/profiles/kalshi_crypto_15m_v2.yaml:")
        report.append(f"   - universe.max_spread_cents: 100 → {self.recommended_max_spread}")
        report.append(f"   - momentum_fvg.spread_gate_cents: 30 → {self.recommended_spread_gate}")
        report.append(f"   - guardrails.min_spread_gate_cents: 30 → {self.recommended_min_spread_gate}")
        report.append("")
        report.append("2. Update hardcoded thresholds in Python files:")
        report.append("   - merid/event_venues/kalshi/models.py: _SPREAD_THRESHOLD_CENTS")
        report.append("   - merid/event_venues/kalshi/microstructure.py: WIDE_SPREAD_THRESHOLD")
        report.append("")
        report.append("3. Update test assertions:")
        report.append("   - Change all assertions expecting 100c to 20c")
        report.append("   - Update spread_gate assertions from 30c to 10c")
        report.append("")
        report.append("4. Verify alignment with 10-75c entry price range:")
        report.append("   - Ensure spread thresholds don't exceed 50% of midpoint entry")
        report.append("   - Consider 15c max spread if 20c proves too permissive")
        report.append("")
        
        return "\n".join(report)

def main():
    """Main entry point."""
    auditor = SpreadThresholdAuditor()
    
    print("Auditing spread threshold configuration...")
    print()
    
    auditor.audit_profile_yaml()
    auditor.audit_python_files()
    auditor.audit_test_files()
    auditor.check_entry_price_alignment()
    
    report = auditor.generate_report()
    print(report)
    
    # Save report to file
    report_path = Path("output/spread_threshold_audit_report.txt")
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(report, encoding='utf-8')
    print(f"\nReport saved to: {report_path}")
    
    # Exit with error code if critical issues found
    critical_count = sum(1 for issue in auditor.issues if issue.severity == "CRITICAL")
    if critical_count > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
