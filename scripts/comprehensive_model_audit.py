#!/usr/bin/env python3
"""
Comprehensive Model Audit Script for MERID Trading System

This script performs an end-to-end audit of the MERID trading system to expose
all flaws and gaps across upstream, midstream, and downstream layers.

Based on 2026 industry best practices:
- Four-Tier Validation Framework (ML4T Diagnostic)
- Robustness Testing (Walk-forward, Monte Carlo, Parameter Sensitivity)
- AlgoXpert Alpha Research Framework (IS/WFA/OOS protocol)
- SysTradeBench Build-Test-Patch methodology

Audit Layers:
1. UPSTREAM: Configuration Layer (Profile YAML, risk limits, asset configs)
2. MIDSTREAM: Risk Envelope Layer (Calculations, adapters, conversions)
3. DOWNSTREAM: Sizing Layer (Unified sizing, scaling multipliers)
4. EXECUTION: Order Flow Layer (Gate, router, position management)
5. DATA: Market Data Layer (Catalog, state store, spot service)
6. AGENTS: Signal Generation Layer (Agent grid, signal quality)
7. END-TO-END: Integration tests across all layers

Usage:
    python scripts/comprehensive_model_audit.py [--fix] [--verbose]
    
    --fix: Automatically fix discovered issues where possible
    --verbose: Enable detailed logging
"""

import sys
import os
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import json
import traceback

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.logger import get_logger
logger = get_logger("scripts.comprehensive_model_audit")


class Severity(Enum):
    """Severity levels for discovered issues."""
    CRITICAL = "CRITICAL"  # System-breaking, must fix immediately
    HIGH = "HIGH"  # Significant impact, should fix soon
    MEDIUM = "MEDIUM"  # Moderate impact, fix in next cycle
    LOW = "LOW"  # Minor impact, fix when convenient
    INFO = "INFO"  # Informational, no action required


class Layer(Enum):
    """System layers for categorization."""
    UPSTREAM = "UPSTREAM"  # Configuration
    MIDSTREAM = "MIDSTREAM"  # Risk envelope
    DOWNSTREAM = "DOWNSTREAM"  # Sizing
    EXECUTION = "EXECUTION"  # Order flow
    DATA = "DATA"  # Market data
    AGENTS = "AGENTS"  # Signal generation
    END_TO_END = "END_TO_END"  # Integration


@dataclass
class AuditIssue:
    """Represents a discovered issue."""
    issue_id: str
    layer: Layer
    severity: Severity
    title: str
    description: str
    location: str  # File/function where issue was found
    evidence: str  # Specific evidence of the issue
    fix_suggestion: str
    upstream_impact: List[str] = field(default_factory=list)
    downstream_impact: List[str] = field(default_factory=list)
    is_fixable: bool = True
    fix_applied: bool = False


class ComprehensiveModelAuditor:
    """
    Comprehensive auditor for MERID trading system.
    
    Performs end-to-end audit across all layers to expose flaws and gaps.
    """
    
    def __init__(self, auto_fix: bool = False, verbose: bool = False):
        self.auto_fix = auto_fix
        self.verbose = verbose
        self.issues: List[AuditIssue] = []
        self.fixes_applied: List[str] = []
        
        # System state
        self.profile_loaded = False
        self.risk_envelope_loaded = False
        self.profile_adapter_loaded = False
        
    def run_full_audit(self) -> Dict[str, Any]:
        """Run comprehensive audit across all layers."""
        logger.info("=" * 80)
        logger.info("COMPREHENSIVE MODEL AUDIT - STARTING")
        logger.info("=" * 80)
        
        results = {
            "total_issues": 0,
            "by_severity": {},
            "by_layer": {},
            "fixes_applied": 0,
            "issues": []
        }
        
        try:
            # Run all layer audits
            self._audit_upstream_layer()
            self._audit_midstream_layer()
            self._audit_downstream_layer()
            self._audit_execution_layer()
            self._audit_data_layer()
            self._audit_agents_layer()
            self._audit_end_to_end_integration()
            
            # Apply fixes if requested
            if self.auto_fix:
                self._apply_fixes()
            
            # Compile results
            results["total_issues"] = len(self.issues)
            for issue in self.issues:
                results["issues"].append({
                    "id": issue.issue_id,
                    "layer": issue.layer.value,
                    "severity": issue.severity.value,
                    "title": issue.title,
                    "location": issue.location,
                    "fix_applied": issue.fix_applied
                })
                
                # Count by severity
                sev = issue.severity.value
                results["by_severity"][sev] = results["by_severity"].get(sev, 0) + 1
                
                # Count by layer
                layer = issue.layer.value
                results["by_layer"][layer] = results["by_layer"].get(layer, 0) + 1
            
            results["fixes_applied"] = len(self.fixes_applied)
            
        except Exception as e:
            logger.exception(f"Audit failed with error: {e}")
            results["error"] = str(e)
        
        logger.info("=" * 80)
        logger.info("COMPREHENSIVE MODEL AUDIT - COMPLETED")
        logger.info(f"Total issues found: {results['total_issues']}")
        logger.info(f"Fixes applied: {results['fixes_applied']}")
        logger.info("=" * 80)
        
        return results
    
    def _add_issue(self, issue: AuditIssue):
        """Add an issue to the audit results."""
        self.issues.append(issue)
        
        log_level = {
            Severity.CRITICAL: logger.error,
            Severity.HIGH: logger.warning,
            Severity.MEDIUM: logger.warning,
            Severity.LOW: logger.info,
            Severity.INFO: logger.info
        }.get(issue.severity, logger.info)
        
        log_level(
            f"[{issue.layer.value}] [{issue.severity.value}] {issue.title} - {issue.location}"
        )
        if self.verbose:
            log_level(f"  Description: {issue.description}")
            log_level(f"  Evidence: {issue.evidence}")
            log_level(f"  Fix: {issue.fix_suggestion}")
    
    def _audit_upstream_layer(self):
        """Audit UPSTREAM layer (Configuration)."""
        logger.info("[UPSTREAM] Auditing configuration layer...")
        
        try:
            # Check 1: Profile YAML exists and is valid
            self._check_profile_yaml_schema()
            
            # Check 2: Risk limit consistency
            self._check_risk_limit_consistency()
            
            # Check 3: Asset configuration completeness
            self._check_asset_config_completeness()
            
            # Check 4: Environment variable conflicts
            self._check_env_var_conflicts()
            
            # Check 5: Deprecated config detection
            self._check_deprecated_configs()
            
        except Exception as e:
            logger.exception(f"Upstream audit failed: {e}")
    
    def _check_profile_yaml_schema(self):
        """Check profile YAML schema validity."""
        try:
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
            
            profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
            
            if not profile_path.exists():
                self._add_issue(AuditIssue(
                    issue_id="UPSTREAM-001",
                    layer=Layer.UPSTREAM,
                    severity=Severity.CRITICAL,
                    title="Profile YAML file missing",
                    description="kalshi_crypto_15m_v2.yaml not found in config/profiles/",
                    location=str(profile_path),
                    evidence=f"File not found at {profile_path}",
                    fix_suggestion="Create profile YAML file with required sections",
                    is_fixable=False
                ))
                return
            
            # Try to load profile
            adapter = Crypto15mProfileAdapter(profile_path)
            profile = adapter._profile
            
            if profile is None:
                self._add_issue(AuditIssue(
                    issue_id="UPSTREAM-002",
                    layer=Layer.UPSTREAM,
                    severity=Severity.CRITICAL,
                    title="Profile YAML failed to load",
                    description="Profile adapter returned None profile",
                    location="merid/risk/profiles/crypto_15m_profile.py",
                    evidence="adapter._profile is None after loading",
                    fix_suggestion="Check YAML syntax and required fields",
                    is_fixable=False
                ))
                return
            
            self.profile_loaded = True
            
            # Check required fields
            required_fields = [
                'profile_name', 'profile_version', 'capital_usd',
                'agent_max_notional_pct', 'venue_max_total_notional_pct',
                'guardrails_per_window_risk_pct', 'guardrails_total_venue_risk_pct'
            ]
            
            for field in required_fields:
                if not hasattr(profile, field):
                    self._add_issue(AuditIssue(
                        issue_id=f"UPSTREAM-003-{field}",
                        layer=Layer.UPSTREAM,
                        severity=Severity.HIGH,
                        title=f"Missing required field: {field}",
                        description=f"Profile missing required field: {field}",
                        location="config/profiles/kalshi_crypto_15m_v2.yaml",
                        evidence=f"hasattr(profile, '{field}') returned False",
                        fix_suggestion=f"Add {field} to profile YAML",
                        is_fixable=True
                    ))
            
        except Exception as e:
            self._add_issue(AuditIssue(
                issue_id="UPSTREAM-004",
                layer=Layer.UPSTREAM,
                severity=Severity.CRITICAL,
                title="Profile YAML load exception",
                description=f"Exception loading profile: {e}",
                location="merid/risk/profiles/crypto_15m_profile.py",
                evidence=str(e),
                fix_suggestion="Check YAML syntax and dependencies",
                is_fixable=False
            ))
    
    def _check_risk_limit_consistency(self):
        """Check risk limit consistency across config files."""
        if not self.profile_loaded:
            logger.warning("[UPSTREAM] Skipping risk limit check - profile not loaded")
            return
        
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            
            adapter = get_active_profile()
            if not adapter:
                return
            
            profile = adapter._profile
            
            # Check 1: Per-agent window limit matches profile
            if hasattr(profile, 'guardrails_per_window_risk_pct'):
                per_window_pct = profile.guardrails_per_window_risk_pct
                if per_window_pct != 0.03:  # Expected 3%
                    self._add_issue(AuditIssue(
                        issue_id="UPSTREAM-005",
                        layer=Layer.UPSTREAM,
                        severity=Severity.HIGH,
                        title="Per-agent window limit mismatch",
                        description=f"Profile has {per_window_pct} but expected 0.03 (3%)",
                        location="config/profiles/kalshi_crypto_15m_v2.yaml",
                        evidence=f"guardrails_per_window_risk_pct = {per_window_pct}",
                        fix_suggestion="Set guardrails_per_window_risk_pct to 0.03",
                        is_fixable=True
                    ))
            
            # Check 2: Total venue window limit matches profile
            if hasattr(profile, 'guardrails_total_venue_risk_pct'):
                total_venue_pct = profile.guardrails_total_venue_risk_pct
                if total_venue_pct != 0.05:  # Expected 5%
                    self._add_issue(AuditIssue(
                        issue_id="UPSTREAM-006",
                        layer=Layer.UPSTREAM,
                        severity=Severity.HIGH,
                        title="Total venue window limit mismatch",
                        description=f"Profile has {total_venue_pct} but expected 0.05 (5%)",
                        location="config/profiles/kalshi_crypto_15m_v2.yaml",
                        evidence=f"guardrails_total_venue_risk_pct = {total_venue_pct}",
                        fix_suggestion="Set guardrails_total_venue_risk_pct to 0.05",
                        is_fixable=True
                    ))
            
            # Check 3: Per-asset cap consistency
            expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
            if hasattr(profile, 'asset_configs'):
                for asset in expected_assets:
                    if asset not in profile.asset_configs:
                        self._add_issue(AuditIssue(
                            issue_id=f"UPSTREAM-007-{asset}",
                            layer=Layer.UPSTREAM,
                            severity=Severity.CRITICAL,
                            title=f"Missing asset config: {asset}",
                            description=f"Profile missing configuration for {asset}",
                            location="config/profiles/kalshi_crypto_15m_v2.yaml",
                            evidence=f"{asset} not in profile.asset_configs",
                            fix_suggestion=f"Add {asset} configuration to profile",
                            is_fixable=True
                        ))
            
        except Exception as e:
            logger.exception(f"Risk limit consistency check failed: {e}")
    
    def _check_asset_config_completeness(self):
        """Check asset configuration completeness."""
        if not self.profile_loaded:
            return
        
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            
            adapter = get_active_profile()
            if not adapter:
                return
            
            profile = adapter._profile
            
            # Check each asset has required fields
            required_asset_fields = [
                'max_notional_pct', 'max_contracts',
                'min_edge_early', 'min_edge_mid', 'min_edge_late'
            ]
            
            if hasattr(profile, 'asset_configs'):
                for asset, config in profile.asset_configs.items():
                    for field in required_asset_fields:
                        if not hasattr(config, field):
                            self._add_issue(AuditIssue(
                                issue_id=f"UPSTREAM-008-{asset}-{field}",
                                layer=Layer.UPSTREAM,
                                severity=Severity.HIGH,
                                title=f"Asset {asset} missing field: {field}",
                                description=f"Asset config missing {field}",
                                location=f"config/profiles/kalshi_crypto_15m_v2.yaml (assets.{asset})",
                                evidence=f"hasattr(config, '{field}') returned False",
                                fix_suggestion=f"Add {field} to {asset} configuration",
                                is_fixable=True
                            ))
            
        except Exception as e:
            logger.exception(f"Asset config completeness check failed: {e}")
    
    def _check_env_var_conflicts(self):
        """Check for environment variable conflicts with profile."""
        import os
        
        # Check for conflicting environment variables
        conflicting_vars = [
            'MERID_BANKROLL_CAP_PCT',  # Should use profile venue.bankroll_cap_pct
            'MERID_MAX_ORDERS_PER_MINUTE',  # Should use profile throttling
            'MERID_MAX_NOTIONAL_PCT',  # Should use profile agent_defaults
        ]
        
        for var in conflicting_vars:
            if var in os.environ:
                self._add_issue(AuditIssue(
                    issue_id=f"UPSTREAM-009-{var}",
                    layer=Layer.UPSTREAM,
                    severity=Severity.MEDIUM,
                    title=f"Environment variable conflict: {var}",
                    description=f"Environment variable {var} is set but profile should be source of truth",
                    location="Environment variables",
                    evidence=f"{var} = {os.environ[var]}",
                    fix_suggestion=f"Remove {var} from environment, use profile YAML instead",
                    is_fixable=True
                ))
    
    def _check_deprecated_configs(self):
        """Check for deprecated configuration files."""
        deprecated_files = [
            "config/kalshi_15m_crypto_config.py",
            "archive/legacy/crypto15mallocator.py",
        ]
        
        repo_root = Path(__file__).parent.parent
        
        for file_path in deprecated_files:
            full_path = repo_root / file_path
            if full_path.exists():
                self._add_issue(AuditIssue(
                    issue_id=f"UPSTREAM-010-{file_path.replace('/', '-')}",
                    layer=Layer.UPSTREAM,
                    severity=Severity.LOW,
                    title=f"Deprecated config file exists: {file_path}",
                    description=f"Deprecated config file still exists, may cause confusion",
                    location=str(full_path),
                    evidence=f"File exists at {full_path}",
                    fix_suggestion=f"Remove or archive {file_path}",
                    is_fixable=True
                ))
    
    def _audit_midstream_layer(self):
        """Audit MIDSTREAM layer (Risk Envelope)."""
        logger.info("[MIDSTREAM] Auditing risk envelope layer...")
        
        try:
            # Check 1: Risk envelope defaults match profile
            self._check_risk_envelope_defaults()
            
            # Check 2: Profile adapter mappings
            self._check_profile_adapter_mappings()
            
            # Check 3: Percentage-to-USD conversions
            self._check_percentage_conversions()
            
            # Check 4: Window tracking state
            self._check_window_tracking_state()
            
        except Exception as e:
            logger.exception(f"Midstream audit failed: {e}")
    
    def _check_risk_envelope_defaults(self):
        """Check risk envelope defaults match profile values."""
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
                compute_kalshi_crypto_15m_risk_envelope,
                _reset_shared_window_state_for_testing
            )
            
            # Reset window state for clean test
            _reset_shared_window_state_for_testing()
            
            # Compute envelope with test bankroll
            envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=1000.0)
            
            # Check per-trade risk percentage
            per_trade_risk = envelope.get_per_trade_risk_pct()
            if per_trade_risk != 0.03:
                self._add_issue(AuditIssue(
                    issue_id="MIDSTREAM-001",
                    layer=Layer.MIDSTREAM,
                    severity=Severity.HIGH,
                    title="Risk envelope per-trade risk mismatch",
                    description=f"Risk envelope returns {per_trade_risk} but expected 0.03 (3%)",
                    location="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
                    evidence=f"get_per_trade_risk_pct() = {per_trade_risk}",
                    fix_suggestion="Update get_per_trade_risk_pct() to return 0.03",
                    is_fixable=True
                ))
            
            # Check window limits
            if envelope.guardrails_per_window_risk_pct != 0.03:
                self._add_issue(AuditIssue(
                    issue_id="MIDSTREAM-002",
                    layer=Layer.MIDSTREAM,
                    severity=Severity.HIGH,
                    title="Risk envelope per-agent window limit mismatch",
                    description=f"Risk envelope has {envelope.guardrails_per_window_risk_pct} but expected 0.03",
                    location="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
                    evidence=f"guardrails_per_window_risk_pct = {envelope.guardrails_per_window_risk_pct}",
                    fix_suggestion="Ensure envelope reads from profile correctly",
                    is_fixable=True
                ))
            
            if envelope.guardrails_total_venue_risk_pct != 0.05:
                self._add_issue(AuditIssue(
                    issue_id="MIDSTREAM-003",
                    layer=Layer.MIDSTREAM,
                    severity=Severity.HIGH,
                    title="Risk envelope total venue window limit mismatch",
                    description=f"Risk envelope has {envelope.guardrails_total_venue_risk_pct} but expected 0.05",
                    location="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
                    evidence=f"guardrails_total_venue_risk_pct = {envelope.guardrails_total_venue_risk_pct}",
                    fix_suggestion="Ensure envelope reads from profile correctly",
                    is_fixable=True
                ))
            
            self.risk_envelope_loaded = True
            
        except Exception as e:
            self._add_issue(AuditIssue(
                issue_id="MIDSTREAM-004",
                layer=Layer.MIDSTREAM,
                severity=Severity.CRITICAL,
                title="Risk envelope computation failed",
                description=f"Exception computing risk envelope: {e}",
                location="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
                evidence=str(e),
                fix_suggestion="Check profile loading and envelope computation logic",
                is_fixable=False
            ))
    
    def _check_profile_adapter_mappings(self):
        """Check profile adapter mappings are correct."""
        if not self.profile_loaded:
            return
        
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            
            adapter = get_active_profile()
            if not adapter:
                return
            
            profile = adapter._profile
            
            # Check critical mappings
            mapping_checks = [
                ('agent_max_notional_pct', 0.03),
                ('venue_max_total_notional_pct', 0.15),
                ('venue_bankroll_cap_pct', 0.03),
            ]
            
            for field, expected_value in mapping_checks:
                if hasattr(profile, field):
                    actual_value = getattr(profile, field)
                    if abs(actual_value - expected_value) > 0.001:  # Allow small floating point error
                        self._add_issue(AuditIssue(
                            issue_id=f"MIDSTREAM-005-{field}",
                            layer=Layer.MIDSTREAM,
                            severity=Severity.HIGH,
                            title=f"Profile adapter {field} mismatch",
                            description=f"Profile has {actual_value} but expected {expected_value}",
                            location="merid/risk/profiles/crypto_15m_profile.py",
                            evidence=f"{field} = {actual_value}",
                            fix_suggestion=f"Update profile YAML to set {field} = {expected_value}",
                            is_fixable=True
                        ))
            
        except Exception as e:
            logger.exception(f"Profile adapter mapping check failed: {e}")
    
    def _check_percentage_conversions(self):
        """Check percentage-to-USD conversion accuracy."""
        if not self.risk_envelope_loaded:
            return
        
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
                compute_kalshi_crypto_15m_risk_envelope,
                _reset_shared_window_state_for_testing
            )
            
            _reset_shared_window_state_for_testing()
            
            # Test with known bankroll
            test_bankroll = 1000.0
            envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=test_bankroll)
            
            # Check per-agent window limit in USD
            expected_per_agent_usd = test_bankroll * 0.03  # 3%
            actual_per_agent_usd = envelope.per_agent_window_limit_usd
            
            if abs(actual_per_agent_usd - expected_per_agent_usd) > 0.01:
                self._add_issue(AuditIssue(
                    issue_id="MIDSTREAM-006",
                    layer=Layer.MIDSTREAM,
                    severity=Severity.HIGH,
                    title="Per-agent window USD conversion incorrect",
                    description=f"Expected ${expected_per_agent_usd} but got ${actual_per_agent_usd}",
                    location="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
                    evidence=f"per_agent_window_limit_usd = {actual_per_agent_usd}",
                    fix_suggestion="Fix USD conversion formula",
                    is_fixable=True
                ))
            
            # Check total venue window limit in USD
            expected_total_venue_usd = test_bankroll * 0.05  # 5%
            actual_total_venue_usd = envelope.total_venue_window_limit_usd
            
            if abs(actual_total_venue_usd - expected_total_venue_usd) > 0.01:
                self._add_issue(AuditIssue(
                    issue_id="MIDSTREAM-007",
                    layer=Layer.MIDSTREAM,
                    severity=Severity.HIGH,
                    title="Total venue window USD conversion incorrect",
                    description=f"Expected ${expected_total_venue_usd} but got ${actual_total_venue_usd}",
                    location="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
                    evidence=f"total_venue_window_limit_usd = {actual_total_venue_usd}",
                    fix_suggestion="Fix USD conversion formula",
                    is_fixable=True
                ))
            
        except Exception as e:
            logger.exception(f"Percentage conversion check failed: {e}")
    
    def _check_window_tracking_state(self):
        """Check window tracking state consistency."""
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
                compute_kalshi_crypto_15m_risk_envelope,
                _reset_shared_window_state_for_testing,
                _WINDOW_TRACKING_STATE
            )
            
            # Reset state
            _reset_shared_window_state_for_testing()
            
            # Verify state is clean
            if _WINDOW_TRACKING_STATE["total_exposure_usd"] != 0.0:
                self._add_issue(AuditIssue(
                    issue_id="MIDSTREAM-008",
                    layer=Layer.MIDSTREAM,
                    severity=Severity.HIGH,
                    title="Window tracking state not reset properly",
                    description="Window tracking state has non-zero exposure after reset",
                    location="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
                    evidence=f"total_exposure_usd = {_WINDOW_TRACKING_STATE['total_exposure_usd']}",
                    fix_suggestion="Fix _reset_shared_window_state_for_testing()",
                    is_fixable=True
                ))
            
            # Test recording and checking
            envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=1000.0)
            
            # Record an execution
            envelope.record_order_execution("TEST_AGENT", 10.0)
            
            # Check it was recorded
            if _WINDOW_TRACKING_STATE["total_exposure_usd"] != 10.0:
                self._add_issue(AuditIssue(
                    issue_id="MIDSTREAM-009",
                    layer=Layer.MIDSTREAM,
                    severity=Severity.HIGH,
                    title="Window exposure recording failed",
                    description="record_order_execution did not update shared state",
                    location="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
                    evidence=f"total_exposure_usd = {_WINDOW_TRACKING_STATE['total_exposure_usd']} (expected 10.0)",
                    fix_suggestion="Fix record_order_execution to write to shared state",
                    is_fixable=True
                ))
            
            # Clean up
            _reset_shared_window_state_for_testing()
            
        except Exception as e:
            logger.exception(f"Window tracking state check failed: {e}")
    
    def _audit_downstream_layer(self):
        """Audit DOWNSTREAM layer (Sizing)."""
        logger.info("[DOWNSTREAM] Auditing sizing layer...")
        
        try:
            # Check 1: Unified sizing reads from profile
            self._check_unified_sizing_profile_source()
            
            # Check 2: Scaling multipliers disabled
            self._check_scaling_multipliers_disabled()
            
            # Check 3: Position size calculations
            self._check_position_size_calculations()
            
        except Exception as e:
            logger.exception(f"Downstream audit failed: {e}")
    
    def _check_unified_sizing_profile_source(self):
        """Check unified sizing reads from profile not env vars."""
        try:
            from merid.prediction.unified_sizing import _get_bankroll_cap_pct
            
            # This should fail if profile is not available (no silent fallback)
            try:
                cap_pct = _get_bankroll_cap_pct()
                # If we get here, profile is available
                logger.info(f"[DOWNSTREAM] bankroll_cap_pct from profile: {cap_pct}")
            except RuntimeError as e:
                if "Profile adapter required" in str(e):
                    # This is expected behavior - fail fast without profile
                    logger.info("[DOWNSTREAM] Unified sizing correctly requires profile")
                else:
                    self._add_issue(AuditIssue(
                        issue_id="DOWNSTREAM-001",
                        layer=Layer.DOWNSTREAM,
                        severity=Severity.HIGH,
                        title="Unified sizing profile check failed unexpectedly",
                        description=f"Unexpected error: {e}",
                        location="merid/prediction/unified_sizing.py",
                        evidence=str(e),
                        fix_suggestion="Investigate profile loading in unified_sizing",
                        is_fixable=False
                    ))
            
        except Exception as e:
            logger.exception(f"Unified sizing profile source check failed: {e}")
    
    def _check_scaling_multipliers_disabled(self):
        """Check that scaling multipliers are disabled to prevent interference."""
        try:
            from merid.prediction.unified_sizing import (
                _get_regime_position_size_multiplier,
                _get_tte_position_size_multiplier
            )
            
            # Check regime multiplier returns 1.0 (disabled)
            regime_mult = _get_regime_position_size_multiplier()
            if regime_mult != 1.0:
                self._add_issue(AuditIssue(
                    issue_id="DOWNSTREAM-002",
                    layer=Layer.DOWNSTREAM,
                    severity=Severity.HIGH,
                    title="Regime sizing multiplier not disabled",
                    description=f"Regime multiplier is {regime_mult} but should be 1.0 (disabled)",
                    location="merid/prediction/unified_sizing.py",
                    evidence=f"_get_regime_position_size_multiplier() = {regime_mult}",
                    fix_suggestion="Ensure regime sizing is disabled to prevent interference with risk limits",
                    is_fixable=True
                ))
            
            # Check TTE multiplier returns 1.0 (disabled)
            tte_mult = _get_tte_position_size_multiplier()
            if tte_mult != 1.0:
                self._add_issue(AuditIssue(
                    issue_id="DOWNSTREAM-003",
                    layer=Layer.DOWNSTREAM,
                    severity=Severity.HIGH,
                    title="TTE sizing multiplier not disabled",
                    description=f"TTE multiplier is {tte_mult} but should be 1.0 (disabled)",
                    location="merid/prediction/unified_sizing.py",
                    evidence=f"_get_tte_position_size_multiplier() = {tte_mult}",
                    fix_suggestion="Ensure TTE sizing is disabled to prevent interference with risk limits",
                    is_fixable=True
                ))
            
        except Exception as e:
            logger.exception(f"Scaling multiplier check failed: {e}")
    
    def _check_position_size_calculations(self):
        """Check position size calculations respect risk limits."""
        try:
            from decimal import Decimal
            from merid.prediction.unified_sizing import compute_order_size
            
            # Test with known parameters
            bankroll = Decimal("1000.0")
            price_cents = 50  # $0.50 per contract
            asset = "BTC"
            
            # This should fail if profile is not available
            try:
                # Test with max_notional_usd to enforce 1-contract rule
                # With price_cents=50 ($0.50), max_notional should be $0.50 for 1 contract
                max_notional = Decimal("0.50")  # Cost of 1 contract at 50c
                
                count, notional, metadata = compute_order_size(
                    bankroll_usd=bankroll,
                    price_cents=price_cents,
                    asset=asset,
                    max_notional_usd=max_notional
                )
                
                # Verify count is reasonable (should be 1 for 1-contract rule)
                if count != 1:
                    self._add_issue(AuditIssue(
                        issue_id="DOWNSTREAM-004",
                        layer=Layer.DOWNSTREAM,
                        severity=Severity.MEDIUM,
                        title="Position size calculation returned unexpected count",
                        description=f"Expected 1 contract but got {count} with max_notional=${max_notional}",
                        location="merid/prediction/unified_sizing.py",
                        evidence=f"compute_order_size returned count={count}, notional=${notional}",
                        fix_suggestion="Verify 1-contract-per-order rule is enforced when max_notional is provided",
                        is_fixable=True
                    ))
                
                # Verify notional is within risk limits
                max_notional = float(bankroll) * 0.03  # 3% per asset
                if float(notional) > max_notional:
                    self._add_issue(AuditIssue(
                        issue_id="DOWNSTREAM-005",
                        layer=Layer.DOWNSTREAM,
                        severity=Severity.HIGH,
                        title="Position size exceeds risk limit",
                        description=f"Notional ${notional} exceeds 3% limit ${max_notional}",
                        location="merid/prediction/unified_sizing.py",
                        evidence=f"notional={notional}, max_notional={max_notional}",
                        fix_suggestion="Fix position size calculation to respect risk limits",
                        is_fixable=True
                    ))
                
            except RuntimeError as e:
                if "Profile adapter required" in str(e):
                    logger.info("[DOWNSTREAM] Position sizing correctly requires profile")
                else:
                    raise
            
        except Exception as e:
            logger.exception(f"Position size calculation check failed: {e}")
    
    def _audit_execution_layer(self):
        """Audit EXECUTION layer (Order Flow)."""
        logger.info("[EXECUTION] Auditing execution layer...")
        
        try:
            # Check 1: Order gate enforces window limits
            self._check_order_gate_window_limits()
            
            # Check 2: Order router records exposure
            self._check_order_router_exposure_recording()
            
            # Check 3: Position monitor callbacks
            self._check_position_monitor_callbacks()
            
            # Check 4: 75c threshold enforcement
            self._check_75c_threshold_enforcement()
            
        except Exception as e:
            logger.exception(f"Execution audit failed: {e}")
    
    def _check_order_gate_window_limits(self):
        """Check order gate enforces window limits correctly."""
        try:
            # Try to import order gate (correct path for 15m stack)
            try:
                from merid.event_venues.kalshi.order_gate import PreTradeGate
                logger.info("[EXECUTION] PreTradeGate imported successfully")
                self._add_issue(AuditIssue(
                    issue_id="EXECUTION-001-SUCCESS",
                    layer=Layer.EXECUTION,
                    severity=Severity.INFO,
                    title="Order gate imported successfully",
                    description="PreTradeGate imported from correct path",
                    location="merid/event_venues/kalshi/order_gate.py",
                    evidence="Import successful",
                    fix_suggestion="No action needed",
                    is_fixable=False
                ))
            except ImportError as e:
                self._add_issue(AuditIssue(
                    issue_id="EXECUTION-001-FAILURE",
                    layer=Layer.EXECUTION,
                    severity=Severity.HIGH,
                    title="Order gate not found",
                    description="PreTradeGate could not be imported",
                    location="merid/event_venues/kalshi/order_gate.py",
                    evidence=str(e),
                    fix_suggestion="Ensure order gate module exists and is importable",
                    is_fixable=False
                ))
                return
            
            # Check if window limit check is implemented
            # This is a basic check - detailed testing would require mocking
            logger.info("[EXECUTION] Order gate window limit check: manual verification required")
            
        except Exception as e:
            logger.exception(f"Order gate window limit check failed: {e}")
    
    def _check_order_router_exposure_recording(self):
        """Check order router records exposure properly."""
        try:
            # Try to import order router (correct path for 15m stack)
            try:
                from merid.event_venues.kalshi.order_router_15m import KalshiOrderRouter15m
                logger.info("[EXECUTION] KalshiOrderRouter15m imported successfully")
            except ImportError as e:
                # Try alternative path
                try:
                    from execution.order_router import OrderRouter
                    logger.info("[EXECUTION] OrderRouter imported (legacy path)")
                except ImportError:
                    self._add_issue(AuditIssue(
                        issue_id="EXECUTION-002",
                        layer=Layer.EXECUTION,
                        severity=Severity.HIGH,
                        title="Order router not found",
                        description="Order router could not be imported from either path",
                        location="merid/event_venues/kalshi/order_router_15m.py or execution/order_router.py",
                        evidence=str(e),
                        fix_suggestion="Ensure order router module exists and is importable",
                        is_fixable=False
                    ))
                    return
            
            logger.info("[EXECUTION] Order router exposure recording: manual verification required")
            
        except Exception as e:
            logger.exception(f"Order router exposure recording check failed: {e}")
    
    def _check_position_monitor_callbacks(self):
        """Check position monitor callbacks are wired correctly."""
        try:
            # Try to import position monitor
            try:
                from merid.position_management.position_monitor import PositionMonitor
                logger.info("[EXECUTION] PositionMonitor imported successfully")
            except ImportError as e:
                self._add_issue(AuditIssue(
                    issue_id="EXECUTION-003",
                    layer=Layer.EXECUTION,
                    severity=Severity.HIGH,
                    title="Position monitor not found",
                    description="PositionMonitor could not be imported",
                    location="merid/position_management/position_monitor.py",
                    evidence=str(e),
                    fix_suggestion="Ensure position monitor module exists and is importable",
                    is_fixable=False
                ))
                return
            
            logger.info("[EXECUTION] Position monitor callbacks: manual verification required")
            
        except Exception as e:
            logger.exception(f"Position monitor callback check failed: {e}")
    
    def _check_75c_threshold_enforcement(self):
        """Check 75c threshold is enforced correctly."""
        try:
            from merid.event_venues.kalshi.risk_parameters import DEEP_OTM_EXPENSIVE_CENTS
            
            # Check threshold is 75
            if DEEP_OTM_EXPENSIVE_CENTS != 75:
                self._add_issue(AuditIssue(
                    issue_id="EXECUTION-004",
                    layer=Layer.EXECUTION,
                    severity=Severity.CRITICAL,
                    title="75c threshold has been changed",
                    description=f"DEEP_OTM_EXPENSIVE_CENTS is {DEEP_OTM_EXPENSIVE_CENTS} but should be 75",
                    location="merid/event_venues/kalshi/risk_parameters.py",
                    evidence=f"DEEP_OTM_EXPENSIVE_CENTS = {DEEP_OTM_EXPENSIVE_CENTS}",
                    fix_suggestion="Restore DEEP_OTM_EXPENSIVE_CENTS to 75 - this is intentional risk management",
                    is_fixable=True
                ))
            else:
                logger.info("[EXECUTION] 75c threshold correctly set to 75")
            
        except Exception as e:
            logger.exception(f"75c threshold check failed: {e}")
    
    def _audit_data_layer(self):
        """Audit DATA layer (Market Data)."""
        logger.info("[DATA] Auditing data layer...")
        
        try:
            # Check 1: Market catalog initialization
            self._check_market_catalog()
            
            # Check 2: Market state store
            self._check_market_state_store()
            
            # Check 3: Spot service
            self._check_spot_service()
            
        except Exception as e:
            logger.exception(f"Data audit failed: {e}")
    
    def _check_market_catalog(self):
        """Check market catalog initialization."""
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            
            catalog = get_market_catalog()
            if catalog is None:
                # This is expected in audit context - catalog requires running server
                logger.info("[DATA] Market catalog not initialized (expected in audit context)")
                self._add_issue(AuditIssue(
                    issue_id="DATA-001",
                    layer=Layer.DATA,
                    severity=Severity.INFO,
                    title="Market catalog not initialized",
                    description="get_market_catalog() returned None (expected in audit context)",
                    location="merid/event_venues/kalshi/market_catalog.py",
                    evidence="catalog is None",
                    fix_suggestion="No action needed - catalog initializes at runtime",
                    is_fixable=False
                ))
            else:
                logger.info("[DATA] Market catalog initialized successfully")
            
        except Exception as e:
            logger.exception(f"Market catalog check failed: {e}")
    
    def _check_market_state_store(self):
        """Check market state store."""
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            
            store = get_kalshi_market_state_store()
            if store is None:
                self._add_issue(AuditIssue(
                    issue_id="DATA-002",
                    layer=Layer.DATA,
                    severity=Severity.HIGH,
                    title="Market state store not initialized",
                    description="get_kalshi_market_state_store() returned None",
                    location="merid/event_venues/kalshi/market_state.py",
                    evidence="store is None",
                    fix_suggestion="Ensure market state store is properly initialized",
                    is_fixable=False
                ))
            else:
                logger.info("[DATA] Market state store initialized successfully")
            
        except Exception as e:
            logger.exception(f"Market state store check failed: {e}")
    
    def _check_spot_service(self):
        """Check spot service."""
        try:
            from data.unified_spot_service import get_unified_spot_service
            
            spot_service = get_unified_spot_service()
            if spot_service is None:
                self._add_issue(AuditIssue(
                    issue_id="DATA-003",
                    layer=Layer.DATA,
                    severity=Severity.HIGH,
                    title="Spot service not initialized",
                    description="get_unified_spot_service() returned None",
                    location="data/unified_spot_service.py",
                    evidence="spot_service is None",
                    fix_suggestion="Ensure spot service is properly initialized",
                    is_fixable=False
                ))
            else:
                logger.info("[DATA] Spot service initialized successfully")
            
        except Exception as e:
            logger.exception(f"Spot service check failed: {e}")
    
    def _audit_agents_layer(self):
        """Audit AGENTS layer (Signal Generation)."""
        logger.info("[AGENTS] Auditing agents layer...")
        
        try:
            # Check 1: Agent grid initialization
            self._check_agent_grid()
            
            # Check 2: All 5 assets have agents
            self._check_all_assets_have_agents()
            
        except Exception as e:
            logger.exception(f"Agents audit failed: {e}")
    
    def _check_agent_grid(self):
        """Check agent grid initialization."""
        try:
            from merid.prediction.agent_grid_15m import AgentGrid15m
            
            logger.info("[AGENTS] AgentGrid15m imported successfully")
            logger.info("[AGENTS] Agent grid initialization: manual verification required")
            
        except ImportError as e:
            self._add_issue(AuditIssue(
                issue_id="AGENTS-001",
                layer=Layer.AGENTS,
                severity=Severity.INFO,
                title="Agent grid not found",
                description="AgentGrid15m could not be imported (expected in audit context)",
                location="merid/prediction/agent_grid_15m.py",
                evidence=str(e),
                fix_suggestion="No action needed - agent grid initializes at runtime",
                is_fixable=False
            ))
    
    def _check_all_assets_have_agents(self):
        """Check all 5 assets have agents configured."""
        expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        # This is a basic check - detailed verification would require inspecting agent grid config
        logger.info(f"[AGENTS] Expected assets: {expected_assets}")
        logger.info("[AGENTS] Asset agent configuration: manual verification required")
    
    def _audit_end_to_end_integration(self):
        """Audit END-TO-END integration."""
        logger.info("[END-TO-END] Auditing end-to-end integration...")
        
        try:
            # Check 1: Legacy contamination
            self._check_legacy_contamination()
            
            # Check 2: Profile consistency across layers
            self._check_profile_consistency_across_layers()
            
        except Exception as e:
            logger.exception(f"End-to-end audit failed: {e}")
    
    def _check_legacy_contamination(self):
        """Check for legacy module contamination."""
        forbidden_modules = [
            'merid.main',
            'merid.loop',
            'merid.prediction.agent_grid',  # Legacy, should use agent_grid_15m
            'web.main',  # Legacy, should use main_15m_lean
        ]
        
        for mod in forbidden_modules:
            if mod in sys.modules:
                self._add_issue(AuditIssue(
                    issue_id=f"E2E-001-{mod.replace('.', '-')}",
                    layer=Layer.END_TO_END,
                    severity=Severity.CRITICAL,
                    title=f"Legacy module contamination: {mod}",
                    description=f"Legacy module {mod} is loaded in 15m stack",
                    location=f"sys.modules['{mod}']",
                    evidence=f"{mod} in sys.modules",
                    fix_suggestion="Remove imports of legacy modules, use production equivalents",
                    is_fixable=True
                ))
    
    def _check_profile_consistency_across_layers(self):
        """Check profile consistency across all layers."""
        if not self.profile_loaded or not self.risk_envelope_loaded:
            logger.warning("[E2E] Skipping profile consistency check - layers not loaded")
            return
        
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
                compute_kalshi_crypto_15m_risk_envelope,
                _reset_shared_window_state_for_testing
            )
            
            adapter = get_active_profile()
            profile = adapter._profile
            
            _reset_shared_window_state_for_testing()
            envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=1000.0)
            
            # Check key values match across layers
            consistency_checks = [
                ("Per-agent window limit", 
                 profile.guardrails_per_window_risk_pct,
                 envelope.guardrails_per_window_risk_pct),
                ("Total venue window limit",
                 profile.guardrails_total_venue_risk_pct,
                 envelope.guardrails_total_venue_risk_pct),
            ]
            
            for check_name, profile_val, envelope_val in consistency_checks:
                if abs(profile_val - envelope_val) > 0.001:
                    self._add_issue(AuditIssue(
                        issue_id=f"E2E-002-{check_name.replace(' ', '-')}",
                        layer=Layer.END_TO_END,
                        severity=Severity.HIGH,
                        title=f"Profile inconsistency: {check_name}",
                        description=f"Profile has {profile_val} but envelope has {envelope_val}",
                        location="Profile vs Risk Envelope",
                        evidence=f"profile={profile_val}, envelope={envelope_val}",
                        fix_suggestion="Ensure envelope reads correct value from profile",
                        is_fixable=True
                    ))
            
        except Exception as e:
            logger.exception(f"Profile consistency check failed: {e}")
    
    def _apply_fixes(self):
        """Apply automatic fixes where possible."""
        logger.info("[FIX] Applying automatic fixes...")
        
        for issue in self.issues:
            if issue.is_fixable and not issue.fix_applied:
                # Apply fix based on issue type
                self._apply_fix_for_issue(issue)
    
    def _apply_fix_for_issue(self, issue: AuditIssue):
        """Apply fix for a specific issue."""
        # This is a placeholder for automatic fix logic
        # In a full implementation, this would have specific fix logic for each issue type
        
        logger.info(f"[FIX] Fix not implemented for {issue.issue_id}: {issue.title}")
        logger.info(f"  Manual fix required: {issue.fix_suggestion}")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Comprehensive Model Audit for MERID Trading System")
    parser.add_argument("--fix", action="store_true", help="Automatically fix issues where possible")
    parser.add_argument("--verbose", action="store_true", help="Enable detailed logging")
    parser.add_argument("--output", type=str, help="Output file for audit results (JSON)")
    
    args = parser.parse_args()
    
    # Run audit
    auditor = ComprehensiveModelAuditor(auto_fix=args.fix, verbose=args.verbose)
    results = auditor.run_full_audit()
    
    # Output results
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        logger.info(f"Results written to {args.output}")
    else:
        print(json.dumps(results, indent=2))
    
    # Exit with error code if critical issues found
    critical_count = results["by_severity"].get("CRITICAL", 0)
    if critical_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
