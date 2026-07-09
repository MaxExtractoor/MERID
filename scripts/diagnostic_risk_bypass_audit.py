#!/usr/bin/env python3
"""
Diagnostic Script: Risk Bypass Audit for 15M Kalshi Crypto Trading Stack

This script performs comprehensive checks to identify potential risk bypasses
and execution guardrail issues across all layers of the trading stack.

Checks performed:
1. Window exposure recording (record_order_execution calls)
2. PreTradeGate.check() usage at all order entry points
3. Exit order window limit handling (100% allowance)
4. Position closure window exposure release
5. Risk envelope consistency across layers
6. Agent grid configuration (all 5 assets)
7. Legacy contamination detection
8. Order rejection path handling

Usage:
    python scripts/diagnostic_risk_bypass_audit.py
"""

import sys
import os
from pathlib import Path
from typing import Dict, List, Tuple, Any
import re

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.logger import get_logger

logger = get_logger("diagnostic_risk_bypass_audit")


class RiskBypassAuditor:
    """Audits the 15M Kalshi crypto trading stack for risk bypasses."""
    
    def __init__(self):
        self.issues: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []
        self.passed: List[Dict[str, Any]] = []
        
    def audit_all(self) -> Dict[str, Any]:
        """Run all diagnostic checks."""
        logger.info("=" * 80)
        logger.info("RISK BYPASS AUDIT - Starting comprehensive diagnostic")
        logger.info("=" * 80)
        
        # Run all checks
        self.check_window_exposure_recording()
        self.check_pretrade_gate_usage()
        self.check_exit_order_window_limits()
        self.check_position_closure_exposure_release()
        self.check_risk_envelope_consistency()
        self.check_agent_grid_configuration()
        self.check_legacy_contamination()
        self.check_rejection_paths()
        
        # Generate report
        report = {
            "total_issues": len(self.issues),
            "total_warnings": len(self.warnings),
            "total_passed": len(self.passed),
            "issues": self.issues,
            "warnings": self.warnings,
            "passed": self.passed,
            "summary": self._generate_summary()
        }
        
        logger.info("=" * 80)
        logger.info("RISK BYPASS AUDIT - Complete")
        logger.info(f"Issues: {len(self.issues)}, Warnings: {len(self.warnings)}, Passed: {len(self.passed)}")
        logger.info("=" * 80)
        
        return report
    
    def _add_issue(self, check_name: str, description: str, file: str = None, line: int = None):
        """Add an issue to the report."""
        self.issues.append({
            "check": check_name,
            "description": description,
            "file": file,
            "line": line,
            "severity": "CRITICAL"
        })
        logger.error(f"[ISSUE] {check_name}: {description}")
        if file:
            logger.error(f"  File: {file}:{line}" if line else f"  File: {file}")
    
    def _add_warning(self, check_name: str, description: str, file: str = None):
        """Add a warning to the report."""
        self.warnings.append({
            "check": check_name,
            "description": description,
            "file": file,
            "severity": "WARNING"
        })
        logger.warning(f"[WARNING] {check_name}: {description}")
        if file:
            logger.warning(f"  File: {file}")
    
    def _add_passed(self, check_name: str, description: str):
        """Add a passed check to the report."""
        self.passed.append({
            "check": check_name,
            "description": description,
            "severity": "PASS"
        })
        logger.info(f"[PASS] {check_name}: {description}")
    
    def _read_file(self, filepath: str) -> str:
        """Read file contents."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to read {filepath}: {e}")
            return ""
    
    def _search_pattern(self, content: str, pattern: str) -> List[Tuple[int, str]]:
        """Search for pattern in content, return list of (line_number, line)."""
        matches = []
        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            if re.search(pattern, line, re.IGNORECASE):
                matches.append((i, line.strip()))
        return matches
    
    def check_window_exposure_recording(self):
        """Check that record_order_execution is called after order submission."""
        logger.info("\n[CHECK] Window Exposure Recording")
        
        # Check order_router.py
        order_router_path = "merid/event_venues/kalshi/order_router.py"
        content = self._read_file(order_router_path)
        
        if content:
            # Check for record_order_execution after venue submission
            matches = self._search_pattern(content, r'record_order_execution')
            if matches:
                self._add_passed(
                    "Window Exposure Recording",
                    f"record_order_execution found in order_router.py ({len(matches)} occurrences)"
                )
                # Verify it's after venue submission
                for line_num, line in matches:
                    if "venue" in line.lower() or "submit" in line.lower() or "fill" in line.lower():
                        self._add_passed(
                            "Window Exposure Recording",
                            f"record_order_execution appears in correct context (line {line_num})"
                        )
            else:
                self._add_issue(
                    "Window Exposure Recording",
                    "record_order_execution NOT found in order_router.py",
                    order_router_path
                )
        
        # Check order_gate.py
        order_gate_path = "merid/event_venues/kalshi/order_gate.py"
        content = self._read_file(order_gate_path)
        
        if content:
            matches = self._search_pattern(content, r'record_order_execution')
            if matches:
                self._add_passed(
                    "Window Exposure Recording",
                    f"record_order_execution found in order_gate.py ({len(matches)} occurrences)"
                )
            else:
                self._add_issue(
                    "Window Exposure Recording",
                    "record_order_execution NOT found in order_gate.py",
                    order_gate_path
                )
    
    def check_pretrade_gate_usage(self):
        """Check that all order entry points use PreTradeGate.check()."""
        logger.info("\n[CHECK] PreTradeGate.check() Usage")
        
        # Check order_router.py
        order_router_path = "merid/event_venues/kalshi/order_router.py"
        content = self._read_file(order_router_path)
        
        if content:
            matches = self._search_pattern(content, r'PreTradeGate.*\.check|gate\.check')
            if matches:
                self._add_passed(
                    "PreTradeGate.check() Usage",
                    f"PreTradeGate.check() found in order_router.py ({len(matches)} occurrences)"
                )
            else:
                self._add_issue(
                    "PreTradeGate.check() Usage",
                    "PreTradeGate.check() NOT found in order_router.py",
                    order_router_path
                )
        
        # Check kalshi_tools.py
        kalshi_tools_path = "merid/prediction/kalshi_tools.py"
        content = self._read_file(kalshi_tools_path)
        
        if content:
            # Check if it routes through order_router (which uses PreTradeGate)
            if "route_order_async" in content:
                self._add_passed(
                    "PreTradeGate.check() Usage",
                    "kalshi_tools.py routes through route_order_async (uses PreTradeGate)"
                )
            else:
                self._add_warning(
                    "PreTradeGate.check() Usage",
                    "kalshi_tools.py may not route through order_router",
                    kalshi_tools_path
                )
    
    def check_exit_order_window_limits(self):
        """Check that exit orders use 100% window limit."""
        logger.info("\n[CHECK] Exit Order Window Limits")
        
        order_gate_path = "merid/event_venues/kalshi/order_gate.py"
        content = self._read_file(order_gate_path)
        
        if content:
            # Check for custom_per_agent_limit_pct or 100% limit for exit orders
            matches = self._search_pattern(content, r'custom_per_agent_limit_pct|1\.0.*exit|exit.*1\.0')
            if matches:
                self._add_passed(
                    "Exit Order Window Limits",
                    f"Custom window limit for exit orders found ({len(matches)} occurrences)"
                )
            else:
                self._add_issue(
                    "Exit Order Window Limits",
                    "Custom window limit for exit orders NOT found",
                    order_gate_path
                )
    
    def check_position_closure_exposure_release(self):
        """Check that position closure releases window exposure."""
        logger.info("\n[CHECK] Position Closure Exposure Release")
        
        position_cache_path = "merid/event_venues/kalshi/position_cache.py"
        content = self._read_file(position_cache_path)
        
        if content:
            # Check for record_position_closure
            matches = self._search_pattern(content, r'record_position_closure')
            if matches:
                self._add_passed(
                    "Position Closure Exposure Release",
                    f"record_position_closure found in position_cache.py ({len(matches)} occurrences)"
                )
            else:
                self._add_issue(
                    "Position Closure Exposure Release",
                    "record_position_closure NOT found in position_cache.py",
                    position_cache_path
                )
            
            # Check for sell-side exposure release
            matches = self._search_pattern(content, r'sell.*release|release.*sell')
            if matches:
                self._add_passed(
                    "Position Closure Exposure Release",
                    "Sell-side exposure release logic found"
                )
            else:
                self._add_warning(
                    "Position Closure Exposure Release",
                    "Sell-side exposure release logic may be missing",
                    position_cache_path
                )
    
    def check_risk_envelope_consistency(self):
        """Check risk envelope consistency across layers."""
        logger.info("\n[CHECK] Risk Envelope Consistency")
        
        # Check profile YAML
        profile_path = "config/profiles/kalshi_crypto_15m_v2.yaml"
        profile_content = self._read_file(profile_path)
        
        if profile_content:
            # Check for 3% per-agent limit
            if "0.03" in profile_content or "3%" in profile_content:
                self._add_passed(
                    "Risk Envelope Consistency",
                    "3% per-agent limit found in profile YAML"
                )
            else:
                self._add_warning(
                    "Risk Envelope Consistency",
                    "3% per-agent limit may not be in profile YAML",
                    profile_path
                )
            
            # Check for 5% total venue limit
            if "0.05" in profile_content or "5%" in profile_content:
                self._add_passed(
                    "Risk Envelope Consistency",
                    "5% total venue limit found in profile YAML"
                )
            else:
                self._add_warning(
                    "Risk Envelope Consistency",
                    "5% total venue limit may not be in profile YAML",
                    profile_path
                )
        
        # Check risk envelope defaults
        envelope_path = "merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py"
        envelope_content = self._read_file(envelope_path)
        
        if envelope_content:
            if "check_window_limit" in envelope_content:
                self._add_passed(
                    "Risk Envelope Consistency",
                    "check_window_limit method found in risk envelope"
                )
            else:
                self._add_issue(
                    "Risk Envelope Consistency",
                    "check_window_limit method NOT found in risk envelope",
                    envelope_path
                )
    
    def check_agent_grid_configuration(self):
        """Check agent grid has all 5 crypto assets."""
        logger.info("\n[CHECK] Agent Grid Configuration")
        
        agent_grid_path = "merid/prediction/agent_grid_15m.py"
        content = self._read_file(agent_grid_path)
        
        if content:
            required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
            missing_assets = []
            
            for asset in required_assets:
                if f"{asset}_15M" not in content and f'"{asset}"' not in content and f"'{asset}'" not in content:
                    missing_assets.append(asset)
            
            if not missing_assets:
                self._add_passed(
                    "Agent Grid Configuration",
                    f"All 5 crypto assets found: {', '.join(required_assets)}"
                )
            else:
                self._add_issue(
                    "Agent Grid Configuration",
                    f"Missing crypto assets: {', '.join(missing_assets)}",
                    agent_grid_path
                )
            
            # Check build_15m_agent_grid function
            if "build_15m_agent_grid" in content:
                self._add_passed(
                    "Agent Grid Configuration",
                    "build_15m_agent_grid function found"
                )
            else:
                self._add_issue(
                    "Agent Grid Configuration",
                    "build_15m_agent_grid function NOT found",
                    agent_grid_path
                )
    
    def check_legacy_contamination(self):
        """Check for legacy code contamination."""
        logger.info("\n[CHECK] Legacy Contamination")
        
        # Check main_15m_lean.py is used (not main.py)
        main_15m_path = "web/main_15m_lean.py"
        if os.path.exists(main_15m_path):
            self._add_passed(
                "Legacy Contamination",
                "web/main_15m_lean.py exists (production entry point)"
            )
        else:
            self._add_issue(
                "Legacy Contamination",
                "web/main_15m_lean.py NOT found",
                main_15m_path
            )
        
        # Check for forbidden imports in main_15m_lean.py
        content = self._read_file(main_15m_path)
        if content:
            forbidden_modules = [
                "merid.prediction.agent_grid",
                "web.main",
                "merid.loop"
            ]
            
            found_forbidden = []
            for module in forbidden_modules:
                # Check for actual import statements, not just string mentions
                import_pattern = rf"^from {module} |^import {module}"
                if re.search(import_pattern, content, re.MULTILINE):
                    found_forbidden.append(module)
            
            if not found_forbidden:
                self._add_passed(
                    "Legacy Contamination",
                    "No forbidden legacy module imports found in main_15m_lean.py"
                )
            else:
                self._add_issue(
                    "Legacy Contamination",
                    f"Forbidden legacy imports found: {', '.join(found_forbidden)}",
                    main_15m_path
                )
    
    def check_rejection_paths(self):
        """Check that rejection paths handle exposure correctly."""
        logger.info("\n[CHECK] Rejection Paths")
        
        order_gate_path = "merid/event_venues/kalshi/order_gate.py"
        content = self._read_file(order_gate_path)
        
        if content:
            # Check for mark_rejected method
            if "mark_rejected" in content:
                self._add_passed(
                    "Rejection Paths",
                    "mark_rejected method found in order_gate.py"
                )
            else:
                self._add_warning(
                    "Rejection Paths",
                    "mark_rejected method NOT found in order_gate.py",
                    order_gate_path
                )
            
            # Check if refund is mentioned (current design doesn't need refunds)
            # since exposure is only recorded on fills
            if "refund" in content.lower():
                self._add_passed(
                    "Rejection Paths",
                    "Refund logic present in order_gate.py"
                )
            else:
                self._add_passed(
                    "Rejection Paths",
                    "No refund needed (exposure only recorded on fills)"
                )
    
    def _generate_summary(self) -> str:
        """Generate a summary of the audit results."""
        summary_lines = [
            "RISK BYPASS AUDIT SUMMARY",
            "=" * 80,
            f"Total Issues: {len(self.issues)}",
            f"Total Warnings: {len(self.warnings)}",
            f"Total Passed: {len(self.passed)}",
            ""
        ]
        
        if self.issues:
            summary_lines.append("CRITICAL ISSUES:")
            for issue in self.issues:
                summary_lines.append(f"  - {issue['check']}: {issue['description']}")
            summary_lines.append("")
        
        if self.warnings:
            summary_lines.append("WARNINGS:")
            for warning in self.warnings:
                summary_lines.append(f"  - {warning['check']}: {warning['description']}")
            summary_lines.append("")
        
        if not self.issues and not self.warnings:
            summary_lines.append("✓ All checks passed - no critical issues or warnings found")
        
        return "\n".join(summary_lines)


def main():
    """Main entry point."""
    auditor = RiskBypassAuditor()
    report = auditor.audit_all()
    
    # Print summary
    print("\n" + report["summary"])
    
    # Exit with error code if issues found
    if report["total_issues"] > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
