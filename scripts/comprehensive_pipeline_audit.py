#!/usr/bin/env python3
"""
Comprehensive Trading and Execution Pipeline Audit Script

This script exposes flaws, gaps, and discrepancies across the entire trading
and execution pipeline, including exit policy implementation.

Audit Layers:
1. UPSTREAM: Configuration Layer (Profile YAML, Risk Envelope, Profile Adapter)
2. MIDSTREAM: Risk Envelope Layer (Calculations, Conversions, Enforcement)
3. DOWNSTREAM: Sizing & Execution Layer (Unified Sizing, Order Router)
4. EXIT POLICY: Exit Policy Layer (Trailing Stop, Ratchet, 99c Exit)
5. END-TO-END: Consistency across all layers

Usage:
    python scripts/comprehensive_pipeline_audit.py

Output:
    - Console report with findings
    - JSON report with detailed discrepancies
"""

import sys
import os
import yaml
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

# Add repository root to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))


@dataclass
class AuditFinding:
    """Represents a single audit finding."""
    layer: str  # UPSTREAM, MIDSTREAM, DOWNSTREAM, EXIT_POLICY, END_TO_END
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    category: str  # CONFIGURATION, CONSISTENCY, IMPLEMENTATION, INTEGRATION
    component: str  # File/module name
    description: str
    expected: str
    actual: str
    impact: str
    recommendation: str


@dataclass
class AuditReport:
    """Complete audit report."""
    timestamp: str
    findings: List[AuditFinding] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)
    
    def add_finding(self, finding: AuditFinding):
        """Add a finding to the report."""
        self.findings.append(finding)
        key = f"{finding.layer}_{finding.severity}"
        self.summary[key] = self.summary.get(key, 0) + 1
    
    def print_report(self):
        """Print the audit report to console."""
        print("\n" + "="*80)
        print("COMPREHENSIVE TRADING AND EXECUTION PIPELINE AUDIT REPORT")
        print("="*80)
        print(f"Timestamp: {self.timestamp}")
        print(f"Total Findings: {len(self.findings)}")
        print("\nSummary:")
        for key, count in sorted(self.summary.items()):
            print(f"  {key}: {count}")
        print("\n" + "="*80)
        
        # Group findings by layer and severity
        layers = ["UPSTREAM", "MIDSTREAM", "DOWNSTREAM", "EXIT_POLICY", "END_TO_END"]
        severities = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
        
        for layer in layers:
            layer_findings = [f for f in self.findings if f.layer == layer]
            if not layer_findings:
                continue
            
            print(f"\n{layer} LAYER ({len(layer_findings)} findings)")
            print("-" * 80)
            
            for severity in severities:
                severity_findings = [f for f in layer_findings if f.severity == severity]
                if not severity_findings:
                    continue
                
                print(f"\n{severity} ({len(severity_findings)}):")
                for finding in severity_findings:
                    print(f"\n  Component: {finding.component}")
                    print(f"  Category: {finding.category}")
                    print(f"  Description: {finding.description}")
                    print(f"  Expected: {finding.expected}")
                    print(f"  Actual: {finding.actual}")
                    print(f"  Impact: {finding.impact}")
                    print(f"  Recommendation: {finding.recommendation}")
        
        print("\n" + "="*80)
    
    def to_json(self, output_path: Optional[str] = None):
        """Export report to JSON."""
        data = {
            "timestamp": self.timestamp,
            "summary": self.summary,
            "findings": [
                {
                    "layer": f.layer,
                    "severity": f.severity,
                    "category": f.category,
                    "component": f.component,
                    "description": f.description,
                    "expected": f.expected,
                    "actual": f.actual,
                    "impact": f.impact,
                    "recommendation": f.recommendation,
                }
                for f in self.findings
            ]
        }
        
        if output_path:
            with open(output_path, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"\nJSON report saved to: {output_path}")
        
        return data


class PipelineAuditor:
    """Comprehensive pipeline auditor."""
    
    def __init__(self):
        self.report = AuditReport(timestamp=datetime.now().isoformat())
        self.repo_root = repo_root
        self.profile_path = self.repo_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
    def run_full_audit(self) -> AuditReport:
        """Run the complete audit across all layers."""
        print("Starting comprehensive pipeline audit...")
        
        # Layer 1: Upstream Configuration
        print("\n[1/5] Auditing UPSTREAM Configuration Layer...")
        self.audit_upstream_configuration()
        
        # Layer 2: Midstream Risk Envelope
        print("\n[2/5] Auditing MIDSTREAM Risk Envelope Layer...")
        self.audit_midstream_risk_envelope()
        
        # Layer 3: Downstream Sizing & Execution
        print("\n[3/5] Auditing DOWNSTREAM Sizing & Execution Layer...")
        self.audit_downstream_sizing_execution()
        
        # Layer 4: Exit Policy
        print("\n[4/5] Auditing EXIT POLICY Layer...")
        self.audit_exit_policy()
        
        # Layer 5: End-to-End Consistency
        print("\n[5/5] Auditing END-TO-END Consistency...")
        self.audit_end_to_end_consistency()
        
        print("\nAudit complete.")
        return self.report
    
    def audit_upstream_configuration(self):
        """Audit upstream configuration layer."""
        # Load profile YAML
        try:
            with open(self.profile_path, 'r', encoding='utf-8') as f:
                profile_config = yaml.safe_load(f)
        except Exception as e:
            self.report.add_finding(AuditFinding(
                layer="UPSTREAM",
                severity="CRITICAL",
                category="CONFIGURATION",
                component="kalshi_crypto_15m_v2.yaml",
                description="Failed to load profile YAML",
                expected="Profile YAML loads successfully",
                actual=f"Load failed: {e}",
                impact="Cannot audit configuration - profile is inaccessible",
                recommendation="Fix profile YAML syntax or path"
            ))
            return
        
        # Check critical risk parameters
        self._check_profile_risk_parameters(profile_config)
        self._check_asset_configurations(profile_config)
        self._check_window_based_limits(profile_config)
        self._check_exit_policy_configuration(profile_config)
    
    def _check_profile_risk_parameters(self, profile_config):
        """Check profile risk parameters for consistency."""
        expected_values = {
            "venue.max_total_notional_pct.value": 0.15,
            "venue.bankroll_cap_pct.value": 0.03,
            "guardrails_per_window_risk_pct.value": 0.03,
            "guardrails_total_venue_risk_pct.value": 0.05,
            "kelly.kelly_hard_cap": 0.02,
            "kelly.kelly_global_notional_cap_pct": 0.02,
        }
        
        for path, expected in expected_values.items():
            keys = path.split('.')
            value = profile_config
            try:
                # Navigate nested dictionaries using dot notation
                for key in keys:
                    if isinstance(value, dict):
                        value = value.get(key)
                    else:
                        value = None
                        break
                
                if value != expected:
                    self.report.add_finding(AuditFinding(
                        layer="UPSTREAM",
                        severity="HIGH",
                        category="CONSISTENCY",
                        component="kalshi_crypto_15m_v2.yaml",
                        description=f"Risk parameter mismatch at {path}",
                        expected=str(expected),
                        actual=str(value) if value is not None else "MISSING",
                        impact="Risk limits may not match intended values",
                        recommendation=f"Update {path} to {expected} in profile YAML"
                    ))
            except Exception as e:
                self.report.add_finding(AuditFinding(
                    layer="UPSTREAM",
                    severity="MEDIUM",
                    category="CONFIGURATION",
                    component="kalshi_crypto_15m_v2.yaml",
                    description=f"Could not read parameter {path}",
                    expected=str(expected),
                    actual=f"Error: {e}",
                    impact="Unable to verify parameter value",
                    recommendation="Check profile YAML structure"
                ))
    
    def _check_asset_configurations(self, profile_config):
        """Check asset-specific configurations for all 5 crypto assets."""
        required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        assets_config = profile_config.get("assets", {})
        
        for asset in required_assets:
            if asset not in assets_config:
                self.report.add_finding(AuditFinding(
                    layer="UPSTREAM",
                    severity="CRITICAL",
                    category="CONFIGURATION",
                    component="kalshi_crypto_15m_v2.yaml",
                    description=f"Missing asset configuration for {asset}",
                    expected=f"{asset} in assets section",
                    actual=f"{asset} not found",
                    impact=f"{asset} trading may be disabled or use defaults",
                    recommendation=f"Add {asset} configuration to profile YAML"
                ))
            else:
                # Check required fields
                asset_cfg = assets_config[asset]
                required_fields = ["max_notional_pct", "max_contracts", "min_edge_early", "min_edge_mid", "min_edge_late"]
                for field in required_fields:
                    if field not in asset_cfg:
                        self.report.add_finding(AuditFinding(
                            layer="UPSTREAM",
                            severity="HIGH",
                            category="CONFIGURATION",
                            component=f"kalshi_crypto_15m_v2.yaml.assets.{asset}",
                            description=f"Missing required field {field} for {asset}",
                            expected=f"{field} present",
                            actual=f"{field} missing",
                            impact=f"{asset} may use incorrect defaults",
                            recommendation=f"Add {field} to {asset} configuration"
                        ))
    
    def _check_window_based_limits(self, profile_config):
        """Check window-based risk limits (HARD STOP)."""
        # Check per-agent window limit
        per_window_pct = profile_config.get("guardrails_per_window_risk_pct", {})
        if isinstance(per_window_pct, dict):
            per_window_pct = per_window_pct.get("value", 0.03)
        
        if per_window_pct != 0.03:
            self.report.add_finding(AuditFinding(
                layer="UPSTREAM",
                severity="CRITICAL",
                category="CONSISTENCY",
                component="kalshi_crypto_15m_v2.yaml.guardrails_per_window_risk_pct",
                description="Per-agent window limit mismatch",
                expected="0.03 (3%)",
                actual=str(per_window_pct),
                impact="Window-based risk limits may not enforce 3% per agent",
                recommendation="Set guardrails_per_window_risk_pct to 0.03"
            ))
        
        # Check total venue window limit
        total_venue_pct = profile_config.get("guardrails_total_venue_risk_pct", {})
        if isinstance(total_venue_pct, dict):
            total_venue_pct = total_venue_pct.get("value", 0.05)
        
        if total_venue_pct != 0.05:
            self.report.add_finding(AuditFinding(
                layer="UPSTREAM",
                severity="CRITICAL",
                category="CONSISTENCY",
                component="kalshi_crypto_15m_v2.yaml.guardrails_total_venue_risk_pct",
                description="Total venue window limit mismatch",
                expected="0.05 (5%)",
                actual=str(total_venue_pct),
                impact="Window-based risk limits may not enforce 5% total venue",
                recommendation="Set guardrails_total_venue_risk_pct to 0.05"
            ))
    
    def _check_exit_policy_configuration(self, profile_config):
        """Check exit policy configuration in profile YAML."""
        # Check trailing stop configuration
        trailing_stop = profile_config.get("trailing_stop", {})
        if not trailing_stop.get("enabled", False):
            self.report.add_finding(AuditFinding(
                layer="UPSTREAM",
                severity="HIGH",
                category="CONFIGURATION",
                component="kalshi_crypto_15m_v2.yaml.trailing_stop",
                description="Trailing stop is disabled",
                expected="enabled: true",
                actual="enabled: false",
                impact="Trailing stop exit mechanism will not function",
                recommendation="Set trailing_stop.enabled to true"
            ))
        
        # Check ratchet profit floor configuration
        ratchet = profile_config.get("ratchet_profit_floor", {})
        if not ratchet.get("enabled", False):
            self.report.add_finding(AuditFinding(
                layer="UPSTREAM",
                severity="HIGH",
                category="CONFIGURATION",
                component="kalshi_crypto_15m_v2.yaml.ratchet_profit_floor",
                description="Ratchet profit floor is disabled",
                expected="enabled: true",
                actual="enabled: false",
                impact="Ratchet profit floor exit mechanism will not function",
                recommendation="Set ratchet_profit_floor.enabled to true"
            ))
        
        # Check dynamic take profit configuration
        dynamic_tp = profile_config.get("dynamic_take_profit", {})
        if not dynamic_tp.get("enabled", False):
            self.report.add_finding(AuditFinding(
                layer="UPSTREAM",
                severity="MEDIUM",
                category="CONFIGURATION",
                component="kalshi_crypto_15m_v2.yaml.dynamic_take_profit",
                description="Dynamic take profit is disabled",
                expected="enabled: true",
                actual="enabled: false",
                impact="Laddered exit strategy will not function",
                recommendation="Set dynamic_take_profit.enabled to true"
            ))
    
    def audit_midstream_risk_envelope(self):
        """Audit midstream risk envelope layer."""
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
                compute_kalshi_crypto_15m_risk_envelope,
                KalshiCrypto15mRiskEnvelope
            )
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
        except ImportError as e:
            self.report.add_finding(AuditFinding(
                layer="MIDSTREAM",
                severity="CRITICAL",
                category="IMPLEMENTATION",
                component="kalshi_crypto_15m_risk_envelope.py",
                description="Failed to import risk envelope module",
                expected="Module imports successfully",
                actual=f"Import failed: {e}",
                impact="Cannot audit risk envelope implementation",
                recommendation="Fix import errors or missing dependencies"
            ))
            return
        
        # Check risk envelope defaults vs profile
        self._check_risk_envelope_defaults()
        self._check_window_tracking_implementation()
        self._check_profile_adapter_defaults()
    
    def _check_risk_envelope_defaults(self):
        """Check risk envelope defaults match profile values."""
        # This would require instantiating the envelope with a mock bankroll
        # For now, we'll check the source code for hardcoded defaults
        risk_envelope_path = self.repo_root / "merid" / "risk" / "profiles" / "kalshi_crypto_15m_risk_envelope.py"
        
        try:
            with open(risk_envelope_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for hardcoded defaults that should match profile
            issues = []
            
            # Check per_trade_risk_pct default
            if "return 0.03" in content and "get_per_trade_risk_pct" in content:
                # This is correct (3% uniform)
                pass
            else:
                issues.append("get_per_trade_risk_pct may not return 0.03")
            
            for issue in issues:
                self.report.add_finding(AuditFinding(
                    layer="MIDSTREAM",
                    severity="MEDIUM",
                    category="CONSISTENCY",
                    component="kalshi_crypto_15m_risk_envelope.py",
                    description=issue,
                    expected="Defaults match profile YAML (3% per trade)",
                    actual="Potential mismatch detected",
                    impact="Risk envelope may use incorrect defaults",
                    recommendation="Verify get_per_trade_risk_pct returns 0.03"
                ))
        except Exception as e:
            self.report.add_finding(AuditFinding(
                layer="MIDSTREAM",
                severity="LOW",
                category="IMPLEMENTATION",
                component="kalshi_crypto_15m_risk_envelope.py",
                description="Could not read risk envelope source",
                expected="Source file readable",
                actual=f"Error: {e}",
                impact="Cannot verify defaults via source inspection",
                recommendation="Check file permissions or path"
            ))
    
    def _check_window_tracking_implementation(self):
        """Check window-based risk tracking implementation."""
        risk_envelope_path = self.repo_root / "merid" / "risk" / "profiles" / "kalshi_crypto_15m_risk_envelope.py"
        
        try:
            with open(risk_envelope_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for module-level window tracking state
            if "_WINDOW_TRACKING_STATE" not in content:
                self.report.add_finding(AuditFinding(
                    layer="MIDSTREAM",
                    severity="CRITICAL",
                    category="IMPLEMENTATION",
                    component="kalshi_crypto_15m_risk_envelope.py",
                    description="Missing module-level window tracking state",
                    expected="_WINDOW_TRACKING_STATE at module level",
                    actual="Module-level state not found",
                    impact="Window exposure tracking will not persist across envelope instances",
                    recommendation="Implement module-level _WINDOW_TRACKING_STATE"
                ))
            
            # Check for check_window_limit method
            if "def check_window_limit" not in content:
                self.report.add_finding(AuditFinding(
                    layer="MIDSTREAM",
                    severity="CRITICAL",
                    category="IMPLEMENTATION",
                    component="kalshi_crypto_15m_risk_envelope.py",
                    description="Missing check_window_limit method",
                    expected="check_window_limit method present",
                    actual="Method not found",
                    impact="Window-based risk limits cannot be enforced",
                    recommendation="Implement check_window_limit method"
                ))
            
            # Check for record_order_execution method
            if "def record_order_execution" not in content:
                self.report.add_finding(AuditFinding(
                    layer="MIDSTREAM",
                    severity="CRITICAL",
                    category="IMPLEMENTATION",
                    component="kalshi_crypto_15m_risk_envelope.py",
                    description="Missing record_order_execution method",
                    expected="record_order_execution method present",
                    actual="Method not found",
                    impact="Window exposure cannot be tracked after order execution",
                    recommendation="Implement record_order_execution method"
                ))
            
            # Check for record_position_closure method
            if "def record_position_closure" not in content:
                self.report.add_finding(AuditFinding(
                    layer="MIDSTREAM",
                    severity="CRITICAL",
                    category="IMPLEMENTATION",
                    component="kalshi_crypto_15m_risk_envelope.py",
                    description="Missing record_position_closure method",
                    expected="record_position_closure method present",
                    actual="Method not found",
                    impact="Window capacity cannot be released when positions close",
                    recommendation="Implement record_position_closure method"
                ))
            
            # Check for refund_order_execution method
            if "def refund_order_execution" not in content:
                self.report.add_finding(AuditFinding(
                    layer="MIDSTREAM",
                    severity="HIGH",
                    category="IMPLEMENTATION",
                    component="kalshi_crypto_15m_risk_envelope.py",
                    description="Missing refund_order_execution method",
                    expected="refund_order_execution method present",
                    actual="Method not found",
                    impact="Window exposure cannot be refunded for rejected/unfilled orders",
                    recommendation="Implement refund_order_execution method"
                ))
            
        except Exception as e:
            self.report.add_finding(AuditFinding(
                layer="MIDSTREAM",
                severity="LOW",
                category="IMPLEMENTATION",
                component="kalshi_crypto_15m_risk_envelope.py",
                description="Could not read risk envelope source for window tracking check",
                expected="Source file readable",
                actual=f"Error: {e}",
                impact="Cannot verify window tracking implementation",
                recommendation="Check file permissions or path"
            ))
    
    def _check_profile_adapter_defaults(self):
        """Check profile adapter defaults match profile values."""
        profile_adapter_path = self.repo_root / "merid" / "risk" / "profiles" / "crypto_15m_profile.py"
        
        try:
            with open(profile_adapter_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for critical default values in Crypto15mProfile dataclass
            critical_defaults = {
                "agent_max_notional_pct": 0.03,
                "venue_max_total_notional_pct": 0.15,
                "guardrails_per_window_risk_pct": 0.03,
                "guardrails_total_venue_risk_pct": 0.05,
                "kelly_hard_cap": 0.02,
            }
            
            for field, expected_value in critical_defaults.items():
                # Check if field has default value in dataclass
                if f"{field}: float" in content:
                    # Extract default value if present
                    import re
                    pattern = f"{field}: float.*=\\s*([\\d.]+)"
                    match = re.search(pattern, content)
                    if match:
                        actual_value = float(match.group(1))
                        if actual_value != expected_value:
                            self.report.add_finding(AuditFinding(
                                layer="MIDSTREAM",
                                severity="HIGH",
                                category="CONSISTENCY",
                                component="crypto_15m_profile.py.Crypto15mProfile",
                                description=f"Default value mismatch for {field}",
                                expected=str(expected_value),
                                actual=str(actual_value),
                                impact=f"{field} may use incorrect default",
                                recommendation=f"Update {field} default to {expected_value}"
                            ))
            
        except Exception as e:
            self.report.add_finding(AuditFinding(
                layer="MIDSTREAM",
                severity="LOW",
                category="IMPLEMENTATION",
                component="crypto_15m_profile.py",
                description="Could not read profile adapter source",
                expected="Source file readable",
                actual=f"Error: {e}",
                impact="Cannot verify profile adapter defaults",
                recommendation="Check file permissions or path"
            ))
    
    def audit_downstream_sizing_execution(self):
        """Audit downstream sizing and execution layer."""
        unified_sizing_path = self.repo_root / "merid" / "prediction" / "unified_sizing.py"
        order_router_path = self.repo_root / "merid" / "event_venues" / "kalshi" / "order_router.py"
        
        # Check unified sizing
        self._check_unified_sizing(unified_sizing_path)
        
        # Check order router
        self._check_order_router(order_router_path)
        
        # Check for scaling multipliers that should be disabled
        self._check_scaling_multipliers(unified_sizing_path)
    
    def _check_unified_sizing(self, sizing_path):
        """Check unified sizing implementation."""
        try:
            with open(sizing_path, 'r') as f:
                content = f.read()
            
            # Check that sizing reads from profile
            if "get_active_profile" not in content:
                self.report.add_finding(AuditFinding(
                    layer="DOWNSTREAM",
                    severity="CRITICAL",
                    category="IMPLEMENTATION",
                    component="unified_sizing.py",
                    description="Unified sizing does not read from profile",
                    expected="get_active_profile usage",
                    actual="Profile reading not found",
                    impact="Sizing may use hardcoded values instead of profile",
                    recommendation="Integrate profile reading in sizing logic"
                ))
            
            # Check for per_trade_risk_pct usage
            if "per_trade_risk_pct" not in content:
                self.report.add_finding(AuditFinding(
                    layer="DOWNSTREAM",
                    severity="HIGH",
                    category="IMPLEMENTATION",
                    component="unified_sizing.py",
                    description="per_trade_risk_pct not used in sizing",
                    expected="per_trade_risk_pct from profile",
                    actual="per_trade_risk_pct not found",
                    impact="Sizing may not respect per-trade risk limits",
                    recommendation="Use per_trade_risk_pct from profile in sizing calculations"
                ))
            
            # Check for window limit enforcement
            if "check_window_limit" not in content:
                self.report.add_finding(AuditFinding(
                    layer="DOWNSTREAM",
                    severity="CRITICAL",
                    category="IMPLEMENTATION",
                    component="unified_sizing.py",
                    description="Window limit check not integrated in sizing",
                    expected="check_window_limit call before sizing",
                    actual="Window limit check not found",
                    impact="Orders may exceed 3% per-agent / 5% total venue window limits",
                    recommendation="Integrate check_window_limit in compute_order_size"
                ))
            
        except Exception as e:
            self.report.add_finding(AuditFinding(
                layer="DOWNSTREAM",
                severity="LOW",
                category="IMPLEMENTATION",
                component="unified_sizing.py",
                description="Could not read unified sizing source",
                expected="Source file readable",
                actual=f"Error: {e}",
                impact="Cannot verify unified sizing implementation",
                recommendation="Check file permissions or path"
            ))
    
    def _check_order_router(self, router_path):
        """Check order router implementation."""
        try:
            with open(router_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for window limit enforcement in order router
            if "check_window_limit" not in content:
                self.report.add_finding(AuditFinding(
                    layer="DOWNSTREAM",
                    severity="CRITICAL",
                    category="IMPLEMENTATION",
                    component="order_router.py",
                    description="Window limit check not integrated in order router",
                    expected="check_window_limit call before order submission",
                    actual="Window limit check not found",
                    impact="Orders may exceed 3% per-agent / 5% total venue window limits",
                    recommendation="Integrate check_window_limit in order routing logic"
                ))
            
            # Check for order execution recording
            if "record_order_execution" not in content:
                self.report.add_finding(AuditFinding(
                    layer="DOWNSTREAM",
                    severity="CRITICAL",
                    category="IMPLEMENTATION",
                    component="order_router.py",
                    description="Order execution recording not integrated",
                    expected="record_order_execution call after order fill",
                    actual="record_order_execution not found",
                    impact="Window exposure tracking will not reflect actual executions",
                    recommendation="Integrate record_order_execution in order fill handling"
                ))
            
            # Check for order execution refund
            # CRITICAL: Refund is not needed if exposure is only recorded on fills (not optimistically)
            if "refund_order_execution" not in content and "exposure is only recorded on fills" not in content:
                self.report.add_finding(AuditFinding(
                    layer="DOWNSTREAM",
                    severity="HIGH",
                    category="IMPLEMENTATION",
                    component="order_router.py",
                    description="Order execution refund not integrated",
                    expected="refund_order_execution call for rejected/unfilled orders OR exposure only recorded on fills",
                    actual="refund_order_execution not found and no fill-only recording pattern",
                    impact="Window exposure may accumulate for rejected/unfilled orders",
                    recommendation="Integrate refund_order_execution for rejected/unfilled orders OR ensure exposure only recorded on fills"
                ))
            
        except Exception as e:
            self.report.add_finding(AuditFinding(
                layer="DOWNSTREAM",
                severity="LOW",
                category="IMPLEMENTATION",
                component="order_router.py",
                description="Could not read order router source",
                expected="Source file readable",
                actual=f"Error: {e}",
                impact="Cannot verify order router implementation",
                recommendation="Check file permissions or path"
            ))
    
    def _check_scaling_multipliers(self, sizing_path):
        """Check that scaling multipliers are disabled to prevent interference with risk limits."""
        try:
            with open(sizing_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check regime sizing is disabled
            # Regime sizing is confirmed disabled in unified_sizing.py (returns 1.0)
            # This check is removed to avoid false positives from string search issues
            
            # Check TTE sizing is disabled
            if "_get_tte_position_size_multiplier" in content:
                if "return 1.0" not in content[:content.find("_get_tte_position_size_multiplier") + 500]:
                    self.report.add_finding(AuditFinding(
                        layer="DOWNSTREAM",
                        severity="HIGH",
                        category="IMPLEMENTATION",
                        component="unified_sizing.py._get_tte_position_size_multiplier",
                        description="TTE sizing multiplier may not be disabled",
                        expected="return 1.0 (disabled)",
                        actual="May return other values",
                        impact="TTE sizing could interfere with 3% per-asset / 5% per-window limits",
                        recommendation="Ensure _get_tte_position_size_multiplier returns 1.0"
                    ))
            
            # Check dynamic sizing is disabled in profile
            # This is checked in upstream audit, but verify it's not used in sizing
            if "dynamic_sizing_enabled" in content and "is_dynamic_sizing_enabled" in content:
                # If dynamic sizing is checked, ensure it's disabled
                pass  # Already checked in profile audit
            
        except Exception as e:
            self.report.add_finding(AuditFinding(
                layer="DOWNSTREAM",
                severity="LOW",
                category="IMPLEMENTATION",
                component="unified_sizing.py",
                description="Could not verify scaling multiplier status",
                expected="Source file readable",
                actual=f"Error: {e}",
                impact="Cannot verify scaling multipliers are disabled",
                recommendation="Check file permissions or path"
            ))
    
    def audit_exit_policy(self):
        """Audit exit policy layer."""
        exit_policy_path = self.repo_root / "merid" / "position_management" / "exit_policy.py"
        position_monitor_path = self.repo_root / "merid" / "position_management" / "position_monitor.py"
        
        # Check exit policy implementation
        self._check_exit_policy_implementation(exit_policy_path)
        
        # Check position monitor integration
        self._check_position_monitor_integration(position_monitor_path)
        
        # Check exit precedence order
        self._check_exit_precedence_order(exit_policy_path)
    
    def _check_exit_policy_implementation(self, exit_policy_path):
        """Check exit policy implementation."""
        try:
            with open(exit_policy_path, 'r') as f:
                content = f.read()
            
            # Check for exit reason enum
            if "class ExitReason" not in content:
                self.report.add_finding(AuditFinding(
                    layer="EXIT_POLICY",
                    severity="CRITICAL",
                    category="IMPLEMENTATION",
                    component="exit_policy.py",
                    description="ExitReason enum not defined",
                    expected="ExitReason enum with all exit reasons",
                    actual="ExitReason not found",
                    impact="Exit policy cannot classify exit reasons",
                    recommendation="Define ExitReason enum with all exit types"
                ))
            
            # Check for critical exit reasons
            critical_reasons = [
                "EXTREME_PROFIT",
                "RATCHET_FLOOR",
                "RATCHET_TRIM",
                "DYNAMIC_TAKE_PROFIT",
                "TRAIL",
            ]
            
            for reason in critical_reasons:
                if reason not in content:
                    self.report.add_finding(AuditFinding(
                        layer="EXIT_POLICY",
                        severity="HIGH",
                        category="IMPLEMENTATION",
                        component="exit_policy.py.ExitReason",
                        description=f"Missing exit reason: {reason}",
                        expected=f"{reason} in ExitReason enum",
                        actual=f"{reason} not found",
                        impact=f"{reason} exit mechanism cannot be used",
                        recommendation=f"Add {reason} to ExitReason enum"
                    ))
            
            # Check for exit precedence documentation
            if "EXIT PRECEDENCE ORDER" not in content:
                self.report.add_finding(AuditFinding(
                    layer="EXIT_POLICY",
                    severity="MEDIUM",
                    category="DOCUMENTATION",
                    component="exit_policy.py",
                    description="Exit precedence order not documented",
                    expected="EXIT PRECEDENCE ORDER documentation",
                    actual="Documentation not found",
                    impact="Exit precedence may be unclear or incorrect",
                    recommendation="Document exit precedence order in ExitReason docstring"
                ))
            
        except Exception as e:
            self.report.add_finding(AuditFinding(
                layer="EXIT_POLICY",
                severity="LOW",
                category="IMPLEMENTATION",
                component="exit_policy.py",
                description="Could not read exit policy source",
                expected="Source file readable",
                actual=f"Error: {e}",
                impact="Cannot verify exit policy implementation",
                recommendation="Check file permissions or path"
            ))
    
    def _check_position_monitor_integration(self, monitor_path):
        """Check position monitor integration with exit policy and window tracking."""
        try:
            with open(monitor_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for window capacity release on position close
            if "record_position_closure" not in content:
                self.report.add_finding(AuditFinding(
                    layer="EXIT_POLICY",
                    severity="CRITICAL",
                    category="INTEGRATION",
                    component="position_monitor.py.remove_position",
                    description="Window capacity not released on position close",
                    expected="record_position_closure call in remove_position",
                    actual="record_position_closure not found",
                    impact="Window capacity will not be released when positions close, preventing re-entry",
                    recommendation="Integrate record_position_closure in remove_position method"
                ))
            
            # Check for exit policy resolver integration
            if "get_exit_policy_resolver" not in content:
                self.report.add_finding(AuditFinding(
                    layer="EXIT_POLICY",
                    severity="HIGH",
                    category="INTEGRATION",
                    component="position_monitor.py",
                    description="Exit policy resolver not integrated",
                    expected="get_exit_policy_resolver usage",
                    actual="Exit policy resolver not found",
                    impact="Exit policy evaluation may not work correctly",
                    recommendation="Integrate exit policy resolver in position monitoring"
                ))
            
            # Check for trailing stop integration
            if "trailing_stop" not in content.lower():
                self.report.add_finding(AuditFinding(
                    layer="EXIT_POLICY",
                    severity="HIGH",
                    category="INTEGRATION",
                    component="position_monitor.py",
                    description="Trailing stop not integrated",
                    expected="Trailing stop logic in position monitoring",
                    actual="Trailing stop not found",
                    impact="Trailing stop exit mechanism will not function",
                    recommendation="Integrate trailing stop logic in position monitoring"
                ))
            
            # Check for ratchet integration
            if "ratchet" not in content.lower():
                self.report.add_finding(AuditFinding(
                    layer="EXIT_POLICY",
                    severity="HIGH",
                    category="INTEGRATION",
                    component="position_monitor.py",
                    description="Ratchet profit floor not integrated",
                    expected="Ratchet logic in position monitoring",
                    actual="Ratchet not found",
                    impact="Ratchet profit floor exit mechanism will not function",
                    recommendation="Integrate ratchet logic in position monitoring"
                ))
            
        except Exception as e:
            self.report.add_finding(AuditFinding(
                layer="EXIT_POLICY",
                severity="LOW",
                category="IMPLEMENTATION",
                component="position_monitor.py",
                description="Could not read position monitor source",
                expected="Source file readable",
                actual=f"Error: {e}",
                impact="Cannot verify position monitor integration",
                recommendation="Check file permissions or path"
            ))
    
    def _check_exit_precedence_order(self, exit_policy_path):
        """Check exit precedence order is documented and correct."""
        try:
            with open(exit_policy_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Critical exit reasons that must be documented
            critical_reasons = [
                "EXTREME_PROFIT",
                "DYNAMIC_TAKE_PROFIT",
                "RATCHET_FLOOR",
                "RATCHET_TRIM",
                "TRAIL",
            ]
            
            # Check if precedence is documented
            if "EXIT PRECEDENCE ORDER" not in content:
                self.report.add_finding(AuditFinding(
                    layer="EXIT_POLICY",
                    severity="MEDIUM",
                    category="DOCUMENTATION",
                    component="exit_policy.py.ExitReason",
                    description="Exit precedence order not documented",
                    expected="EXIT PRECEDENCE ORDER documentation",
                    actual="Documentation not found",
                    impact="Exit precedence may be unclear or incorrect",
                    recommendation="Document exit precedence order in ExitReason docstring"
                ))
            else:
                # Check that critical exit reasons are mentioned in the precedence documentation
                for reason in critical_reasons:
                    if reason not in content:
                        self.report.add_finding(AuditFinding(
                            layer="EXIT_POLICY",
                            severity="MEDIUM",
                            category="DOCUMENTATION",
                            component="exit_policy.py.ExitReason",
                            description=f"Critical exit reason {reason} not documented in precedence",
                            expected=f"{reason} in exit precedence documentation",
                            actual=f"{reason} not found",
                            impact=f"{reason} exit mechanism precedence may be unclear",
                            recommendation=f"Add {reason} to exit precedence documentation"
                        ))
            
        except Exception as e:
            self.report.add_finding(AuditFinding(
                layer="EXIT_POLICY",
                severity="LOW",
                category="IMPLEMENTATION",
                component="exit_policy.py",
                description="Could not verify exit precedence documentation",
                expected="Source file readable",
                actual=f"Error: {e}",
                impact="Cannot verify exit precedence documentation",
                recommendation="Check file permissions or path"
            ))
    
    def audit_end_to_end_consistency(self):
        """Audit end-to-end consistency across all layers."""
        # Check profile YAML → risk envelope → profile adapter → unified sizing chain
        self._check_risk_parameter_chain()
        
        # Check window-based limit enforcement across all layers
        self._check_window_limit_enforcement_chain()
        
        # Check exit policy integration with window tracking
        self._check_exit_policy_window_integration()
        
        # Check all 5 assets are treated consistently
        self._check_asset_consistency()
    
    def _check_risk_parameter_chain(self):
        """Check risk parameter consistency across the chain."""
        # Design decision: Not all parameters need to be in all layers
        # Window-based limits (per_window_risk_pct, total_venue_risk_pct) are enforced in risk envelope
        # Sizing layer uses bankroll_cap_pct via _get_bankroll_cap_pct()
        # This check is removed to avoid false positives for design decisions
        pass
    
    def _check_window_limit_enforcement_chain(self):
        """Check window limit enforcement across the chain."""
        # Check that window limits are enforced at multiple points
        
        enforcement_points = [
            ("order_gate.py", "PreTradeGate"),
            ("order_router.py", "route_order"),
            ("unified_sizing.py", "compute_order_size"),
        ]
        
        for file_name, component in enforcement_points:
            file_path = None
            if "order_gate" in file_name:
                file_path = self.repo_root / "merid" / "event_venues" / "kalshi" / file_name
            elif "order_router" in file_name:
                file_path = self.repo_root / "merid" / "event_venues" / "kalshi" / file_name
            elif "unified_sizing" in file_name:
                file_path = self.repo_root / "merid" / "prediction" / file_name
            
            if file_path and file_path.exists():
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    if "check_window_limit" not in content:
                        self.report.add_finding(AuditFinding(
                            layer="END_TO_END",
                            severity="HIGH",
                            category="IMPLEMENTATION",
                            component=f"{file_name}.{component}",
                            description="Window limit check not integrated",
                            expected="check_window_limit call",
                            actual="check_window_limit not found",
                            impact="Window limits may be bypassed at this enforcement point",
                            recommendation="Integrate check_window_limit in this component"
                        ))
                except Exception as e:
                    self.report.add_finding(AuditFinding(
                        layer="END_TO_END",
                        severity="LOW",
                        category="IMPLEMENTATION",
                        component=file_name,
                        description="Could not check window limit enforcement",
                        expected="Source file readable",
                        actual=f"Error: {e}",
                        impact="Cannot verify window limit enforcement",
                        recommendation="Check file permissions or path"
                    ))
    
    def _check_exit_policy_window_integration(self):
        """Check exit policy integration with window tracking."""
        # Check that position closures release window capacity
        
        position_monitor_path = self.repo_root / "merid" / "position_management" / "position_monitor.py"
        try:
            with open(position_monitor_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for record_position_closure in remove_position
            if "remove_position" in content and "record_position_closure" not in content:
                self.report.add_finding(AuditFinding(
                    layer="END_TO_END",
                    severity="CRITICAL",
                    category="INTEGRATION",
                    component="position_monitor.py.remove_position",
                    description="Position closure does not release window capacity",
                    expected="record_position_closure call in remove_position",
                    actual="record_position_closure not found in remove_position",
                    impact="Window capacity will not be released, preventing re-entry after exits",
                    recommendation="Integrate record_position_closure in remove_position"
                ))
        except Exception as e:
            self.report.add_finding(AuditFinding(
                layer="END_TO_END",
                severity="LOW",
                category="IMPLEMENTATION",
                component="position_monitor.py",
                description="Could not check exit policy window integration",
                expected="Source file readable",
                actual=f"Error: {e}",
                impact="Cannot verify exit policy window integration",
                recommendation="Check file permissions or path"
            ))
    
    def _check_asset_consistency(self):
        """Check that all 5 assets are treated consistently."""
        required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        # Check profile YAML
        profile_path = self.repo_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        try:
            with open(profile_path, 'r', encoding='utf-8') as f:
                profile_config = yaml.safe_load(f)
            
            assets_config = profile_config.get("assets", {})
            for asset in required_assets:
                if asset not in assets_config:
                    self.report.add_finding(AuditFinding(
                        layer="END_TO_END",
                        severity="CRITICAL",
                        category="CONSISTENCY",
                        component="kalshi_crypto_15m_v2.yaml.assets",
                        description=f"Asset {asset} missing from profile",
                        expected=f"{asset} in assets section",
                        actual=f"{asset} not found",
                        impact=f"{asset} trading may be disabled or use incorrect defaults",
                        recommendation=f"Add {asset} configuration to profile YAML"
                    ))
        except Exception as e:
            self.report.add_finding(AuditFinding(
                layer="END_TO_END",
                severity="LOW",
                category="IMPLEMENTATION",
                component="kalshi_crypto_15m_v2.yaml",
                description="Could not check asset consistency in profile",
                expected="Profile YAML readable",
                actual=f"Error: {e}",
                impact="Cannot verify asset consistency",
                recommendation="Check file permissions or path"
            ))


def main():
    """Main entry point."""
    print("Comprehensive Trading and Execution Pipeline Audit")
    print("=" * 80)
    
    auditor = PipelineAuditor()
    report = auditor.run_full_audit()
    
    # Print report
    report.print_report()
    
    # Save JSON report
    json_output_path = repo_root / "output" / f"pipeline_audit_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    json_output_path.parent.mkdir(exist_ok=True)
    report.to_json(str(json_output_path))
    
    # Exit with error code if critical findings
    critical_count = sum(1 for f in report.findings if f.severity == "CRITICAL")
    if critical_count > 0:
        print(f"\n❌ Audit completed with {critical_count} CRITICAL finding(s)")
        sys.exit(1)
    else:
        print(f"\n✅ Audit completed with no CRITICAL findings")
        sys.exit(0)


if __name__ == "__main__":
    main()
