#!/usr/bin/env python3
"""
Edge System Audit Script

Comprehensive audit of the edge system across the entire production stack:
- Upstream: Profile YAML, risk parameters, configuration consistency
- Midstream: Risk envelope calculations, window tracking, agent defaults
- Downstream: Sizing logic, order routing, position management
- End-to-End: Cross-layer consistency validation

Based on 2026 research and industry best practices for trading system validation.
"""

from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from decimal import Decimal
import yaml

# Add repository root to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

from utils.logger import get_logger

logger = get_logger("scripts.edge_system_audit")


@dataclass
class AuditFinding:
    """Represents a single audit finding."""
    layer: str  # "upstream", "midstream", "downstream", "end_to_end"
    category: str  # e.g., "profile_yaml", "risk_envelope", "sizing", "execution"
    severity: str  # "critical", "high", "medium", "low", "info"
    check_name: str
    description: str
    expected: str
    actual: str
    recommendation: str = ""
    file_path: str = ""
    line_number: int = 0


@dataclass
class AuditReport:
    """Complete audit report with all findings."""
    findings: List[AuditFinding] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)
    
    def add_finding(self, finding: AuditFinding):
        self.findings.append(finding)
        
    def get_summary(self) -> Dict[str, int]:
        """Generate summary statistics."""
        summary = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "info": 0,
            "total": len(self.findings)
        }
        for finding in self.findings:
            summary[finding.severity] += 1
        return summary


class EdgeSystemAuditor:
    """Comprehensive edge system auditor."""
    
    def __init__(self, profile_path: Optional[Path] = None):
        """Initialize the auditor.
        
        Args:
            profile_path: Path to profile YAML. If None, uses default kalshi_crypto_15m_v2.yaml
        """
        if profile_path is None:
            profile_path = repo_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        self.profile_path = profile_path
        self.report = AuditReport()
        self.profile_config: Optional[Dict[str, Any]] = None
        
    def load_profile(self) -> bool:
        """Load profile YAML configuration."""
        try:
            with open(self.profile_path, 'r', encoding='utf-8') as f:
                self.profile_config = yaml.safe_load(f)
            logger.info(f"[AUDIT] Loaded profile from {self.profile_path}")
            return True
        except Exception as e:
            logger.error(f"[AUDIT] Failed to load profile: {e}")
            self.report.add_finding(AuditFinding(
                layer="upstream",
                category="profile_yaml",
                severity="critical",
                check_name="profile_load",
                description="Failed to load profile YAML",
                expected="Profile YAML loads successfully",
                actual=f"Load failed: {e}",
                recommendation="Check profile YAML syntax and file path",
                file_path=str(self.profile_path)
            ))
            return False
    
    def run_full_audit(self) -> AuditReport:
        """Run comprehensive edge system audit."""
        logger.info("[AUDIT] Starting comprehensive edge system audit")
        
        # Load profile
        if not self.load_profile():
            return self.report
        
        # Run all audit layers
        self.audit_upstream()
        self.audit_midstream()
        self.audit_downstream()
        self.audit_end_to_end()
        
        # Generate summary
        summary = self.report.get_summary()
        logger.info(f"[AUDIT] Audit complete: {summary}")
        
        return self.report
    
    def audit_upstream(self):
        """Audit upstream layer: Profile YAML, risk parameters, configuration consistency."""
        logger.info("[AUDIT] Auditing upstream layer")
        
        if not self.profile_config:
            logger.error("[AUDIT] Profile not loaded, skipping upstream audit")
            return
        
        # Check 1: Profile YAML structure
        self._check_profile_structure()
        
        # Check 2: Critical risk parameters
        self._check_critical_risk_parameters()
        
        # Check 3: Asset configuration consistency
        self._check_asset_configuration()
        
        # Check 4: Signal generation parameters
        self._check_signal_generation_parameters()
        
        # Check 5: Feature flags consistency
        self._check_feature_flags()
    
    def audit_midstream(self):
        """Audit midstream layer: Risk envelope calculations, window tracking, agent defaults."""
        logger.info("[AUDIT] Auditing midstream layer")
        
        # Check 1: Risk envelope defaults
        self._check_risk_envelope_defaults()
        
        # Check 2: Profile adapter defaults
        self._check_profile_adapter_defaults()
        
        # Check 3: Window-based risk tracking
        self._check_window_based_risk_tracking()
        
        # Check 4: Percentage-to-USD conversions
        self._check_percentage_conversions()
    
    def audit_downstream(self):
        """Audit downstream layer: Sizing logic, order routing, position management."""
        logger.info("[AUDIT] Auditing downstream layer")
        
        # Check 1: Unified sizing logic
        self._check_unified_sizing()
        
        # Check 2: Scaling multipliers (should be disabled)
        self._check_scaling_multipliers()
        
        # Check 3: Order routing logic
        self._check_order_routing()
        
        # Check 4: Position management
        self._check_position_management()
    
    def audit_end_to_end(self):
        """Audit end-to-end: Cross-layer consistency validation."""
        logger.info("[AUDIT] Auditing end-to-end consistency")
        
        # Check 1: Profile → Risk Envelope consistency
        self._check_profile_to_risk_envelope_consistency()
        
        # Check 2: Risk Envelope → Profile Adapter consistency
        self._check_risk_envelope_to_adapter_consistency()
        
        # Check 3: Profile Adapter → Unified Sizing consistency
        self._check_adapter_to_sizing_consistency()
        
        # Check 4: Window limit enforcement across layers
        self._check_window_limit_enforcement()
        
        # Check 5: Asset consistency across all layers
        self._check_asset_consistency()
    
    # ============================================================================
    # Upstream Audit Methods
    # ============================================================================
    
    def _check_profile_structure(self):
        """Check profile YAML has required sections."""
        required_sections = [
            'profile_name',
            'profile_version',
            'description',
            'capital_usd',
            'venue',
            'assets',
            'agent_defaults',
            'kelly',
            'guardrails',
            'contract_caps',
            'risk_policy',
        ]
        
        for section in required_sections:
            if section not in self.profile_config:
                self.report.add_finding(AuditFinding(
                    layer="upstream",
                    category="profile_yaml",
                    severity="critical",
                    check_name="profile_structure",
                    description=f"Missing required section: {section}",
                    expected=f"Section '{section}' present in profile YAML",
                    actual=f"Section '{section}' not found",
                    recommendation=f"Add '{section}' section to profile YAML",
                    file_path=str(self.profile_path)
                ))
    
    def _check_critical_risk_parameters(self):
        """Check critical risk parameters are present and have correct values."""
        critical_params = {
            'guardrails_per_window_risk_pct': 0.03,  # 3% per agent per 15m window
            'guardrails_total_venue_risk_pct': 0.05,  # 5% total per 15m window
            'venue.max_total_notional_pct.value': 0.15,  # 15% total venue cap
            'venue.bankroll_cap_pct.value': 0.03,  # 3% bankroll cap per order
            'kelly.kelly_hard_cap': 0.02,  # 2% Kelly hard cap
            'kelly.kelly_global_notional_cap_pct': 0.02,  # 2% Kelly global notional cap
        }
        
        for param_path, expected_value in critical_params.items():
            actual_value = self._get_nested_value(self.profile_config, param_path)
            
            # Handle nested dict format (e.g., {'value': 0.03, 'description': ...})
            if isinstance(actual_value, dict) and 'value' in actual_value:
                actual_value = actual_value['value']
            
            if actual_value is None:
                self.report.add_finding(AuditFinding(
                    layer="upstream",
                    category="risk_parameters",
                    severity="critical",
                    check_name="critical_risk_param",
                    description=f"Missing critical risk parameter: {param_path}",
                    expected=f"{param_path} = {expected_value}",
                    actual=f"{param_path} not found",
                    recommendation=f"Add {param_path} to profile YAML with value {expected_value}",
                    file_path=str(self.profile_path)
                ))
            elif not self._values_match(actual_value, expected_value):
                self.report.add_finding(AuditFinding(
                    layer="upstream",
                    category="risk_parameters",
                    severity="critical",
                    check_name="critical_risk_param",
                    description=f"Critical risk parameter mismatch: {param_path}",
                    expected=f"{param_path} = {expected_value}",
                    actual=f"{param_path} = {actual_value}",
                    recommendation=f"Update {param_path} to {expected_value} in profile YAML",
                    file_path=str(self.profile_path)
                ))
    
    def _check_asset_configuration(self):
        """Check all 5 crypto assets are configured consistently."""
        required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        assets_config = self.profile_config.get('assets', {})
        
        for asset in required_assets:
            if asset not in assets_config:
                self.report.add_finding(AuditFinding(
                    layer="upstream",
                    category="asset_configuration",
                    severity="critical",
                    check_name="asset_coverage",
                    description=f"Missing asset configuration: {asset}",
                    expected=f"Asset '{asset}' configured in profile YAML",
                    actual=f"Asset '{asset}' not found",
                    recommendation=f"Add configuration for {asset} to assets section",
                    file_path=str(self.profile_path)
                ))
            else:
                # Check asset has required fields
                asset_fields = ['max_notional_pct', 'max_contracts']
                for field in asset_fields:
                    if field not in assets_config[asset]:
                        self.report.add_finding(AuditFinding(
                            layer="upstream",
                            category="asset_configuration",
                            severity="high",
                            check_name="asset_fields",
                            description=f"Missing field for {asset}: {field}",
                            expected=f"Asset '{asset}' has field '{field}'",
                            actual=f"Field '{field}' not found for {asset}",
                            recommendation=f"Add {field} to {asset} configuration",
                            file_path=str(self.profile_path)
                        ))
    
    def _check_signal_generation_parameters(self):
        """Check signal generation parameters are configured."""
        signal_params = {
            'signal_mode': 'momentum_fvg',
        }
        
        for param_path, expected_value in signal_params.items():
            actual_value = self._get_nested_value(self.profile_config, param_path)
            
            if actual_value is None:
                self.report.add_finding(AuditFinding(
                    layer="upstream",
                    category="signal_generation",
                    severity="high",
                    check_name="signal_param",
                    description=f"Missing signal parameter: {param_path}",
                    expected=f"{param_path} = {expected_value}",
                    actual=f"{param_path} not found",
                    recommendation=f"Add {param_path} to profile YAML",
                    file_path=str(self.profile_path)
                ))
            elif actual_value != expected_value:
                self.report.add_finding(AuditFinding(
                    layer="upstream",
                    category="signal_generation",
                    severity="high",
                    check_name="signal_param",
                    description=f"Signal parameter mismatch: {param_path}",
                    expected=f"{param_path} = {expected_value}",
                    actual=f"{param_path} = {actual_value}",
                    recommendation=f"Update {param_path} to {expected_value} in profile YAML",
                    file_path=str(self.profile_path)
                ))
    
    def _check_feature_flags(self):
        """Check feature flags are set correctly."""
        feature_flags = {
            'dynamic_sizing.enabled': False,  # Should be disabled to prevent interference with risk limits
            'correlation_tracking.enabled': False,  # Disabled for 15m crypto prediction markets
            'offset_hedging.enabled': False,  # Disabled - binary hedging inefficient for crypto
        }
        
        for param_path, expected_value in feature_flags.items():
            actual_value = self._get_nested_value(self.profile_config, param_path)
            
            if actual_value is None:
                self.report.add_finding(AuditFinding(
                    layer="upstream",
                    category="feature_flags",
                    severity="medium",
                    check_name="feature_flag",
                    description=f"Missing feature flag: {param_path}",
                    expected=f"{param_path} = {expected_value}",
                    actual=f"{param_path} not found",
                    recommendation=f"Add {param_path} to profile YAML with value {expected_value}",
                    file_path=str(self.profile_path)
                ))
            elif actual_value != expected_value:
                self.report.add_finding(AuditFinding(
                    layer="upstream",
                    category="feature_flags",
                    severity="high",
                    check_name="feature_flag",
                    description=f"Feature flag mismatch: {param_path}",
                    expected=f"{param_path} = {expected_value}",
                    actual=f"{param_path} = {actual_value}",
                    recommendation=f"Update {param_path} to {expected_value} in profile YAML",
                    file_path=str(self.profile_path)
                ))
    
    # ============================================================================
    # Midstream Audit Methods
    # ============================================================================
    
    def _check_risk_envelope_defaults(self):
        """Check risk envelope defaults match profile YAML values."""
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
                compute_kalshi_crypto_15m_risk_envelope
            )
            
            # Compute envelope with test bankroll
            envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=100.0)
            
            # Check critical defaults
            checks = [
                ('guardrails_per_window_risk_pct', 0.03, envelope.guardrails_per_window_risk_pct),
                ('guardrails_total_venue_risk_pct', 0.05, envelope.guardrails_total_venue_risk_pct),
            ]
            
            for param_name, expected, actual in checks:
                if not self._values_match(actual, expected):
                    self.report.add_finding(AuditFinding(
                        layer="midstream",
                        category="risk_envelope",
                        severity="critical",
                        check_name="risk_envelope_default",
                        description=f"Risk envelope default mismatch: {param_name}",
                        expected=f"{param_name} = {expected}",
                        actual=f"{param_name} = {actual}",
                        recommendation="Update risk envelope default to match profile YAML",
                        file_path="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py"
                    ))
                    
        except ImportError as e:
            self.report.add_finding(AuditFinding(
                layer="midstream",
                category="risk_envelope",
                severity="critical",
                check_name="risk_envelope_import",
                description="Failed to import risk envelope module",
                expected="Risk envelope module imports successfully",
                actual=f"Import failed: {e}",
                recommendation="Check risk envelope module imports and dependencies",
                file_path="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py"
            ))
    
    def _check_profile_adapter_defaults(self):
        """Check profile adapter defaults match profile YAML values."""
        try:
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
            
            adapter = Crypto15mProfileAdapter(profile_path=self.profile_path)
            profile = adapter._profile
            
            # Check critical defaults
            checks = [
                ('agent_max_notional_pct', 0.03, profile.agent_max_notional_pct),
                ('venue_max_total_notional_pct', 0.15, profile.venue_max_total_notional_pct),
                ('guardrails_per_window_risk_pct', 0.03, profile.guardrails_per_window_risk_pct),
                ('guardrails_total_venue_risk_pct', 0.05, profile.guardrails_total_venue_risk_pct),
            ]
            
            for param_name, expected, actual in checks:
                if not self._values_match(actual, expected):
                    self.report.add_finding(AuditFinding(
                        layer="midstream",
                        category="profile_adapter",
                        severity="critical",
                        check_name="adapter_default",
                        description=f"Profile adapter default mismatch: {param_name}",
                        expected=f"{param_name} = {expected}",
                        actual=f"{param_name} = {actual}",
                        recommendation="Update profile adapter default to match profile YAML",
                        file_path="merid/risk/profiles/crypto_15m_profile.py"
                    ))
                    
        except ImportError as e:
            self.report.add_finding(AuditFinding(
                layer="midstream",
                category="profile_adapter",
                severity="critical",
                check_name="adapter_import",
                description="Failed to import profile adapter module",
                expected="Profile adapter module imports successfully",
                actual=f"Import failed: {e}",
                recommendation="Check profile adapter module imports and dependencies",
                file_path="merid/risk/profiles/crypto_15m_profile.py"
            ))
    
    def _check_window_based_risk_tracking(self):
        """Check window-based risk tracking is implemented correctly."""
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
                compute_kalshi_crypto_15m_risk_envelope,
                _WINDOW_TRACKING_STATE
            )
            
            # Check window tracking state exists
            if not _WINDOW_TRACKING_STATE:
                self.report.add_finding(AuditFinding(
                    layer="midstream",
                    category="window_tracking",
                    severity="critical",
                    check_name="window_tracking_state",
                    description="Window tracking state not found",
                    expected="Module-level window tracking state exists",
                    actual="Window tracking state not initialized",
                    recommendation="Ensure window tracking state is initialized at module level",
                    file_path="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py"
                ))
            
            # Check envelope has window tracking methods
            envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=100.0)
            
            required_methods = ['check_window_limit', 'record_order_execution', 'record_position_closure']
            for method_name in required_methods:
                if not hasattr(envelope, method_name):
                    self.report.add_finding(AuditFinding(
                        layer="midstream",
                        category="window_tracking",
                        severity="critical",
                        check_name="window_tracking_method",
                        description=f"Missing window tracking method: {method_name}",
                        expected=f"Envelope has method '{method_name}'",
                        actual=f"Method '{method_name}' not found",
                        recommendation=f"Implement {method_name} method in risk envelope",
                        file_path="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py"
                    ))
                    
        except ImportError as e:
            self.report.add_finding(AuditFinding(
                layer="midstream",
                category="window_tracking",
                severity="critical",
                check_name="window_tracking_import",
                description="Failed to import risk envelope for window tracking check",
                expected="Risk envelope imports successfully",
                actual=f"Import failed: {e}",
                recommendation="Check risk envelope module imports",
                file_path="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py"
            ))
    
    def _check_percentage_conversions(self):
        """Check percentage-to-USD conversions are correct."""
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
                compute_kalshi_crypto_15m_risk_envelope
            )
            
            # Test with known bankroll
            test_bankroll = 100.0
            envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=test_bankroll)
            
            # Check per-agent window limit
            expected_per_agent = test_bankroll * 0.03  # 3%
            actual_per_agent = envelope.per_agent_window_limit_usd
            
            if not self._values_match(actual_per_agent, expected_per_agent, tolerance=0.01):
                self.report.add_finding(AuditFinding(
                    layer="midstream",
                    category="percentage_conversion",
                    severity="high",
                    check_name="per_agent_window_conversion",
                    description="Per-agent window limit conversion incorrect",
                    expected=f"per_agent_window_limit_usd = ${expected_per_agent:.2f}",
                    actual=f"per_agent_window_limit_usd = ${actual_per_agent:.2f}",
                    recommendation="Fix percentage-to-USD conversion for per-agent window limit",
                    file_path="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py"
                ))
            
            # Check total venue window limit
            expected_total = test_bankroll * 0.05  # 5%
            actual_total = envelope.total_venue_window_limit_usd
            
            if not self._values_match(actual_total, expected_total, tolerance=0.01):
                self.report.add_finding(AuditFinding(
                    layer="midstream",
                    category="percentage_conversion",
                    severity="high",
                    check_name="total_venue_window_conversion",
                    description="Total venue window limit conversion incorrect",
                    expected=f"total_venue_window_limit_usd = ${expected_total:.2f}",
                    actual=f"total_venue_window_limit_usd = ${actual_total:.2f}",
                    recommendation="Fix percentage-to-USD conversion for total venue window limit",
                    file_path="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py"
                ))
                    
        except ImportError as e:
            self.report.add_finding(AuditFinding(
                layer="midstream",
                category="percentage_conversion",
                severity="high",
                check_name="conversion_import",
                description="Failed to import risk envelope for conversion check",
                expected="Risk envelope imports successfully",
                actual=f"Import failed: {e}",
                recommendation="Check risk envelope module imports",
                file_path="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py"
            ))
    
    # ============================================================================
    # Downstream Audit Methods
    # ============================================================================
    
    def _check_unified_sizing(self):
        """Check unified sizing logic is configured correctly."""
        try:
            from merid.prediction.unified_sizing import (
                _get_bankroll_cap_pct,
                _get_per_trade_risk_pct,
                _get_max_single_order_pct
            )
            
            # Check bankroll cap percentage
            bankroll_cap = _get_bankroll_cap_pct()
            expected_bankroll_cap = Decimal("0.03")  # 3%
            
            if bankroll_cap != expected_bankroll_cap:
                self.report.add_finding(AuditFinding(
                    layer="downstream",
                    category="unified_sizing",
                    severity="critical",
                    check_name="bankroll_cap_pct",
                    description="Bankroll cap percentage mismatch",
                    expected=f"bankroll_cap_pct = {expected_bankroll_cap}",
                    actual=f"bankroll_cap_pct = {bankroll_cap}",
                    recommendation="Update bankroll cap percentage to match profile YAML (3%)",
                    file_path="merid/prediction/unified_sizing.py"
                ))
            
            # Check per-trade risk percentage
            per_trade_risk = _get_per_trade_risk_pct()
            expected_per_trade = Decimal("0.03")  # 3%
            
            if per_trade_risk != expected_per_trade:
                self.report.add_finding(AuditFinding(
                    layer="downstream",
                    category="unified_sizing",
                    severity="critical",
                    check_name="per_trade_risk_pct",
                    description="Per-trade risk percentage mismatch",
                    expected=f"per_trade_risk_pct = {expected_per_trade}",
                    actual=f"per_trade_risk_pct = {per_trade_risk}",
                    recommendation="Update per-trade risk percentage to match profile YAML (3%)",
                    file_path="merid/prediction/unified_sizing.py"
                ))
            
            # Check max single order percentage
            max_single_order = _get_max_single_order_pct()
            expected_max_single = Decimal("0.03")  # 3%
            
            if max_single_order != expected_max_single:
                self.report.add_finding(AuditFinding(
                    layer="downstream",
                    category="unified_sizing",
                    severity="critical",
                    check_name="max_single_order_pct",
                    description="Max single order percentage mismatch",
                    expected=f"max_single_order_pct = {expected_max_single}",
                    actual=f"max_single_order_pct = {max_single_order}",
                    recommendation="Update max single order percentage to match profile YAML (3%)",
                    file_path="merid/prediction/unified_sizing.py"
                ))
                    
        except ImportError as e:
            self.report.add_finding(AuditFinding(
                layer="downstream",
                category="unified_sizing",
                severity="critical",
                check_name="sizing_import",
                description="Failed to import unified sizing module",
                expected="Unified sizing module imports successfully",
                actual=f"Import failed: {e}",
                recommendation="Check unified sizing module imports and dependencies",
                file_path="merid/prediction/unified_sizing.py"
            ))
    
    def _check_scaling_multipliers(self):
        """Check scaling multipliers are disabled to prevent interference with risk limits."""
        try:
            from merid.prediction.unified_sizing import (
                _get_regime_position_size_multiplier,
                _get_tte_position_size_multiplier,
                _is_dynamic_sizing_enabled
            )
            
            # Check regime sizing is disabled
            regime_multiplier = _get_regime_position_size_multiplier()
            if regime_multiplier != 1.0:
                self.report.add_finding(AuditFinding(
                    layer="downstream",
                    category="scaling_multipliers",
                    severity="high",
                    check_name="regime_sizing_disabled",
                    description="Regime-based sizing is not disabled",
                    expected="regime_multiplier = 1.0 (disabled)",
                    actual=f"regime_multiplier = {regime_multiplier}",
                    recommendation="Disable regime-based sizing to prevent interference with risk limits",
                    file_path="merid/prediction/unified_sizing.py"
                ))
            
            # Check TTE sizing is disabled
            tte_multiplier = _get_tte_position_size_multiplier(tte_seconds=300)
            if tte_multiplier != 1.0:
                self.report.add_finding(AuditFinding(
                    layer="downstream",
                    category="scaling_multipliers",
                    severity="high",
                    check_name="tte_sizing_disabled",
                    description="TTE-based sizing is not disabled",
                    expected="tte_multiplier = 1.0 (disabled)",
                    actual=f"tte_multiplier = {tte_multiplier}",
                    recommendation="Disable TTE-based sizing to prevent interference with risk limits",
                    file_path="merid/prediction/unified_sizing.py"
                ))
            
            # Check dynamic sizing is disabled
            dynamic_sizing_enabled = _is_dynamic_sizing_enabled()
            if dynamic_sizing_enabled:
                self.report.add_finding(AuditFinding(
                    layer="downstream",
                    category="scaling_multipliers",
                    severity="high",
                    check_name="dynamic_sizing_disabled",
                    description="Dynamic sizing is enabled",
                    expected="dynamic_sizing_enabled = False",
                    actual=f"dynamic_sizing_enabled = {dynamic_sizing_enabled}",
                    recommendation="Disable dynamic sizing to prevent interference with risk limits",
                    file_path="merid/prediction/unified_sizing.py"
                ))
                    
        except ImportError as e:
            self.report.add_finding(AuditFinding(
                layer="downstream",
                category="scaling_multipliers",
                severity="medium",
                check_name="scaling_import",
                description="Failed to import unified sizing for scaling check",
                expected="Unified sizing imports successfully",
                actual=f"Import failed: {e}",
                recommendation="Check unified sizing module imports",
                file_path="merid/prediction/unified_sizing.py"
            ))
    
    def _check_order_routing(self):
        """Check order routing logic is configured correctly."""
        try:
            from merid.event_venues.kalshi.order_router import (
                check_market_microstructure,
                check_fee_aware_edge
            )
            
            # Check market microstructure function exists
            if not callable(check_market_microstructure):
                self.report.add_finding(AuditFinding(
                    layer="downstream",
                    category="order_routing",
                    severity="high",
                    check_name="market_microstructure",
                    description="Market microstructure check function not callable",
                    expected="check_market_microstructure is callable",
                    actual="check_market_microstructure is not callable",
                    recommendation="Ensure check_market_microstructure function is properly defined",
                    file_path="merid/event_venues/kalshi/order_router.py"
                ))
            
            # Check fee-aware edge function exists
            if not callable(check_fee_aware_edge):
                self.report.add_finding(AuditFinding(
                    layer="downstream",
                    category="order_routing",
                    severity="high",
                    check_name="fee_aware_edge",
                    description="Fee-aware edge check function not callable",
                    expected="check_fee_aware_edge is callable",
                    actual="check_fee_aware_edge is not callable",
                    recommendation="Ensure check_fee_aware_edge function is properly defined",
                    file_path="merid/event_venues/kalshi/order_router.py"
                ))
                    
        except ImportError as e:
            self.report.add_finding(AuditFinding(
                layer="downstream",
                category="order_routing",
                severity="high",
                check_name="routing_import",
                description="Failed to import order router module",
                expected="Order router module imports successfully",
                actual=f"Import failed: {e}",
                recommendation="Check order router module imports and dependencies",
                file_path="merid/event_venues/kalshi/order_router.py"
            ))
    
    def _check_position_management(self):
        """Check position management is configured correctly."""
        try:
            from merid.event_venues.kalshi.position_cache import (
                KalshiPositionCache,
                CachedPosition
            )
            from dataclasses import fields
            
            # Check CachedPosition has required dataclass fields
            required_dataclass_fields = [
                'market_id', 'contracts', 'side', 'avg_price_cents'
            ]
            
            # Check CachedPosition has required properties/methods
            required_members = [
                'notional_usd',  # property
                'apply_fill',  # method
            ]
            
            # Get dataclass field names
            field_names = {f.name for f in fields(CachedPosition)}
            
            for field_name in required_dataclass_fields:
                # Check if field exists in dataclass fields
                if field_name not in field_names:
                    self.report.add_finding(AuditFinding(
                        layer="downstream",
                        category="position_management",
                        severity="high",
                        check_name="position_field",
                        description=f"Missing dataclass field in CachedPosition: {field_name}",
                        expected=f"CachedPosition has dataclass field '{field_name}'",
                        actual=f"Field '{field_name}' not found",
                        recommendation=f"Add {field_name} field to CachedPosition",
                        file_path="merid/event_venues/kalshi/position_cache.py"
                    ))
            
            for member_name in required_members:
                # Check if member exists (property or method)
                if not hasattr(CachedPosition, member_name):
                    self.report.add_finding(AuditFinding(
                        layer="downstream",
                        category="position_management",
                        severity="high",
                        check_name="position_member",
                        description=f"Missing member in CachedPosition: {member_name}",
                        expected=f"CachedPosition has member '{member_name}'",
                        actual=f"Member '{member_name}' not found",
                        recommendation=f"Add {member_name} to CachedPosition",
                        file_path="merid/event_venues/kalshi/position_cache.py"
                    ))
                    
        except ImportError as e:
            self.report.add_finding(AuditFinding(
                layer="downstream",
                category="position_management",
                severity="high",
                check_name="position_import",
                description="Failed to import position cache module",
                expected="Position cache module imports successfully",
                actual=f"Import failed: {e}",
                recommendation="Check position cache module imports and dependencies",
                file_path="merid/event_venues/kalshi/position_cache.py"
            ))
    
    # ============================================================================
    # End-to-End Audit Methods
    # ============================================================================
    
    def _check_profile_to_risk_envelope_consistency(self):
        """Check profile YAML values match risk envelope defaults."""
        if not self.profile_config:
            return
        
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
                compute_kalshi_crypto_15m_risk_envelope
            )
            
            envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=100.0)
            
            # Check consistency for critical parameters
            consistency_checks = [
                ('guardrails_per_window_risk_pct', 
                 self._get_nested_value(self.profile_config, 'guardrails_per_window_risk_pct.value'),
                 envelope.guardrails_per_window_risk_pct),
                ('guardrails_total_venue_risk_pct',
                 self._get_nested_value(self.profile_config, 'guardrails_total_venue_risk_pct.value'),
                 envelope.guardrails_total_venue_risk_pct),
            ]
            
            for param_name, profile_value, envelope_value in consistency_checks:
                if profile_value is not None and not self._values_match(profile_value, envelope_value):
                    self.report.add_finding(AuditFinding(
                        layer="end_to_end",
                        category="consistency",
                        severity="critical",
                        check_name="profile_to_envelope",
                        description=f"Profile YAML and risk envelope mismatch: {param_name}",
                        expected=f"Profile and envelope both have {param_name} = {profile_value}",
                        actual=f"Profile: {profile_value}, Envelope: {envelope_value}",
                        recommendation="Align risk envelope default with profile YAML value",
                        file_path="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py"
                    ))
                    
        except ImportError as e:
            self.report.add_finding(AuditFinding(
                layer="end_to_end",
                category="consistency",
                severity="high",
                check_name="envelope_import",
                description="Failed to import risk envelope for consistency check",
                expected="Risk envelope imports successfully",
                actual=f"Import failed: {e}",
                recommendation="Check risk envelope module imports",
                file_path="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py"
            ))
    
    def _check_risk_envelope_to_adapter_consistency(self):
        """Check risk envelope defaults match profile adapter defaults."""
        try:
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
                compute_kalshi_crypto_15m_risk_envelope
            )
            
            adapter = Crypto15mProfileAdapter(profile_path=self.profile_path)
            profile = adapter._profile
            envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=100.0)
            
            # Check consistency for critical parameters
            consistency_checks = [
                ('guardrails_per_window_risk_pct',
                 profile.guardrails_per_window_risk_pct,
                 envelope.guardrails_per_window_risk_pct),
                ('guardrails_total_venue_risk_pct',
                 profile.guardrails_total_venue_risk_pct,
                 envelope.guardrails_total_venue_risk_pct),
            ]
            
            for param_name, adapter_value, envelope_value in consistency_checks:
                if not self._values_match(adapter_value, envelope_value):
                    self.report.add_finding(AuditFinding(
                        layer="end_to_end",
                        category="consistency",
                        severity="critical",
                        check_name="envelope_to_adapter",
                        description=f"Risk envelope and profile adapter mismatch: {param_name}",
                        expected=f"Envelope and adapter both have {param_name} = {adapter_value}",
                        actual=f"Adapter: {adapter_value}, Envelope: {envelope_value}",
                        recommendation="Align profile adapter default with risk envelope value",
                        file_path="merid/risk/profiles/crypto_15m_profile.py"
                    ))
                    
        except ImportError as e:
            self.report.add_finding(AuditFinding(
                layer="end_to_end",
                category="consistency",
                severity="high",
                check_name="adapter_import",
                description="Failed to import modules for consistency check",
                expected="Modules import successfully",
                actual=f"Import failed: {e}",
                recommendation="Check module imports",
                file_path="merid/risk/profiles/crypto_15m_profile.py"
            ))
    
    def _check_adapter_to_sizing_consistency(self):
        """Check profile adapter defaults match unified sizing behavior."""
        try:
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
            from merid.prediction.unified_sizing import (
                _get_bankroll_cap_pct,
                _get_per_trade_risk_pct
            )
            
            adapter = Crypto15mProfileAdapter(profile_path=self.profile_path)
            profile = adapter._profile
            
            # Check consistency for critical parameters
            consistency_checks = [
                ('bankroll_cap_pct',
                 Decimal(str(profile.venue_bankroll_cap_pct)),
                 _get_bankroll_cap_pct()),
                ('per_trade_risk_pct',
                 Decimal(str(profile.guardrails_per_trade_risk_pct)),
                 _get_per_trade_risk_pct()),
            ]
            
            for param_name, adapter_value, sizing_value in consistency_checks:
                if not self._values_match(adapter_value, sizing_value):
                    self.report.add_finding(AuditFinding(
                        layer="end_to_end",
                        category="consistency",
                        severity="critical",
                        check_name="adapter_to_sizing",
                        description=f"Profile adapter and unified sizing mismatch: {param_name}",
                        expected=f"Adapter and sizing both have {param_name} = {adapter_value}",
                        actual=f"Adapter: {adapter_value}, Sizing: {sizing_value}",
                        recommendation="Align unified sizing with profile adapter value",
                        file_path="merid/prediction/unified_sizing.py"
                    ))
                    
        except ImportError as e:
            self.report.add_finding(AuditFinding(
                layer="end_to_end",
                category="consistency",
                severity="high",
                check_name="sizing_import",
                description="Failed to import modules for consistency check",
                expected="Modules import successfully",
                actual=f"Import failed: {e}",
                recommendation="Check module imports",
                file_path="merid/prediction/unified_sizing.py"
            ))
    
    def _check_window_limit_enforcement(self):
        """Check window-based risk limits are enforced across all layers."""
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
                compute_kalshi_crypto_15m_risk_envelope,
                _reset_shared_window_state_for_testing
            )
            import time
            
            # Reset window state for clean test
            _reset_shared_window_state_for_testing()
            
            envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=100.0)
            
            # Test window limit enforcement
            test_agent_id = "BTC_15M"
            test_order_notional = 2.0  # $2 (within 3% limit of $3)
            current_ts = time.time()  # Use current time to avoid window rollover
            
            allowed, reason = envelope.check_window_limit(
                test_agent_id, test_order_notional, current_ts
            )
            
            # First order should be allowed (no exposure yet)
            if not allowed:
                self.report.add_finding(AuditFinding(
                    layer="end_to_end",
                    category="window_enforcement",
                    severity="critical",
                    check_name="window_limit_check",
                    description="Window limit check incorrectly blocks first order",
                    expected="First order should be allowed (no exposure yet)",
                    actual=f"First order blocked: {reason}",
                    recommendation="Fix window limit check logic",
                    file_path="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py"
                ))
            
            # Test that exceeding limit is blocked
            # Record execution to exceed limit
            envelope.record_order_execution(test_agent_id, test_order_notional)
            
            # Try to exceed per-agent limit (3% of $100 = $3)
            # After first $2 order, another $2 order would exceed $3 limit
            large_order = 2.0  # $2 (would exceed $3 limit after first $2 order)
            allowed, reason = envelope.check_window_limit(test_agent_id, large_order, current_ts)
            
            if allowed:
                self.report.add_finding(AuditFinding(
                    layer="end_to_end",
                    category="window_enforcement",
                    severity="critical",
                    check_name="window_limit_enforcement",
                    description="Window limit enforcement not working - order exceeding limit was allowed",
                    expected="Order exceeding per-agent window limit should be blocked",
                    actual=f"Order exceeding limit was allowed",
                    recommendation="Fix window limit enforcement logic",
                    file_path="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py"
                ))
                    
        except ImportError as e:
            self.report.add_finding(AuditFinding(
                layer="end_to_end",
                category="window_enforcement",
                severity="high",
                check_name="envelope_import",
                description="Failed to import risk envelope for window enforcement check",
                expected="Risk envelope imports successfully",
                actual=f"Import failed: {e}",
                recommendation="Check risk envelope module imports",
                file_path="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py"
            ))
    
    def _check_asset_consistency(self):
        """Check all 5 assets are treated consistently across all layers."""
        required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        # Check profile YAML has all assets
        assets_config = self.profile_config.get('assets', {})
        for asset in required_assets:
            if asset not in assets_config:
                self.report.add_finding(AuditFinding(
                    layer="end_to_end",
                    category="asset_consistency",
                    severity="critical",
                    check_name="asset_coverage",
                    description=f"Asset missing from profile YAML: {asset}",
                    expected=f"All 5 assets (BTC, ETH, SOL, XRP, DOGE) in profile YAML",
                    actual=f"Asset {asset} not found",
                    recommendation=f"Add {asset} to assets section in profile YAML",
                    file_path=str(self.profile_path)
                ))
        
        # Check velocity thresholds are defined in profile adapter (not YAML)
        try:
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
            
            adapter = Crypto15mProfileAdapter(profile_path=self.profile_path)
            profile = adapter._profile
            
            velocity_attrs = [
                'velocity_threshold_btc',
                'velocity_threshold_eth',
                'velocity_threshold_sol',
                'velocity_threshold_xrp',
                'velocity_threshold_doge',
            ]
            
            for attr_name in velocity_attrs:
                if not hasattr(profile, attr_name):
                    self.report.add_finding(AuditFinding(
                        layer="end_to_end",
                        category="asset_consistency",
                        severity="high",
                        check_name="velocity_threshold",
                        description=f"Missing velocity threshold in profile adapter: {attr_name}",
                        expected=f"Velocity threshold defined for all assets in profile adapter",
                        actual=f"{attr_name} not found",
                        recommendation=f"Add {attr_name} to Crypto15mProfile",
                        file_path="merid/risk/profiles/crypto_15m_profile.py"
                    ))
                    
        except ImportError as e:
            self.report.add_finding(AuditFinding(
                layer="end_to_end",
                category="asset_consistency",
                severity="high",
                check_name="adapter_import",
                description="Failed to import profile adapter for velocity check",
                expected="Profile adapter imports successfully",
                actual=f"Import failed: {e}",
                recommendation="Check profile adapter module imports",
                file_path="merid/risk/profiles/crypto_15m_profile.py"
            ))
    
    # ============================================================================
    # Helper Methods
    # ============================================================================
    
    def _get_nested_value(self, data: Dict[str, Any], path: str) -> Any:
        """Get value from nested dictionary using dot notation."""
        keys = path.split('.')
        value = data
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        return value
    
    def _values_match(self, a: Any, b: Any, tolerance: float = 0.0) -> bool:
        """Check if two values match, with optional tolerance for floats."""
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return abs(a - b) <= tolerance
        return a == b
    
    def print_report(self):
        """Print audit report to console."""
        print("\n" + "="*80)
        print("EDGE SYSTEM AUDIT REPORT")
        print("="*80 + "\n")
        
        # Print summary
        summary = self.report.get_summary()
        print("SUMMARY:")
        print(f"  Critical: {summary['critical']}")
        print(f"  High:     {summary['high']}")
        print(f"  Medium:   {summary['medium']}")
        print(f"  Low:      {summary['low']}")
        print(f"  Info:     {summary['info']}")
        print(f"  Total:    {summary['total']}")
        print()
        
        # Print findings by severity
        for severity in ["critical", "high", "medium", "low", "info"]:
            findings = [f for f in self.report.findings if f.severity == severity]
            if findings:
                print(f"\n{severity.upper()} FINDINGS ({len(findings)}):")
                print("-" * 80)
                for i, finding in enumerate(findings, 1):
                    print(f"\n{i}. [{finding.layer.upper()}] {finding.category}")
                    print(f"   Check: {finding.check_name}")
                    print(f"   Description: {finding.description}")
                    print(f"   Expected: {finding.expected}")
                    print(f"   Actual: {finding.actual}")
                    if finding.recommendation:
                        print(f"   Recommendation: {finding.recommendation}")
                    if finding.file_path:
                        print(f"   File: {finding.file_path}")
        
        print("\n" + "="*80)
        print("AUDIT COMPLETE")
        print("="*80 + "\n")
    
    def save_report(self, output_path: Path):
        """Save audit report to JSON file."""
        import json
        from dataclasses import asdict
        
        report_data = {
            "summary": self.report.get_summary(),
            "findings": [asdict(f) for f in self.report.findings]
        }
        
        with open(output_path, 'w') as f:
            json.dump(report_data, f, indent=2)
        
        logger.info(f"[AUDIT] Report saved to {output_path}")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Edge System Audit Script")
    parser.add_argument(
        "--profile",
        type=Path,
        default=None,
        help="Path to profile YAML (default: config/profiles/kalshi_crypto_15m_v2.yaml)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to save JSON report (default: edge_system_audit_report.json)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logger.setLevel("DEBUG")
    
    # Run audit
    auditor = EdgeSystemAuditor(profile_path=args.profile)
    report = auditor.run_full_audit()
    
    # Print report
    auditor.print_report()
    
    # Save report
    if args.output is None:
        output_path = repo_root / "edge_system_audit_report.json"
    else:
        output_path = args.output
    
    auditor.save_report(output_path)
    
    # Exit with error code if critical findings
    summary = report.get_summary()
    if summary['critical'] > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
