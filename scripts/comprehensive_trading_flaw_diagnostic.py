#!/usr/bin/env python3
"""
Comprehensive Trading Flaw Diagnostic Script

This script systematically checks all layers of the MERID 15M Kalshi crypto trading stack
to expose flaws, discrepancies, and configuration issues that may prevent trading execution.

Based on the upstream/midstream/downstream audit process and risk configuration consistency guidelines.

Usage:
    python scripts/comprehensive_trading_flaw_diagnostic.py

Output:
    - Detailed report of all discrepancies found
    - Severity levels (CRITICAL, HIGH, MEDIUM, LOW)
    - Recommended fixes for each issue
"""

import sys
import os
from pathlib import Path
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass
from enum import Enum

# Add repository root to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))


class Severity(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class DiagnosticIssue:
    """A single diagnostic issue found during analysis."""
    severity: Severity
    category: str
    description: str
    location: str
    recommendation: str
    actual_value: Any = None
    expected_value: Any = None


class TradingFlawDiagnostic:
    """Comprehensive diagnostic for trading execution flaws."""
    
    def __init__(self):
        self.issues: List[DiagnosticIssue] = []
        self.repo_root = repo_root
        
    def add_issue(self, severity: Severity, category: str, description: str, 
                  location: str, recommendation: str, actual_value: Any = None, 
                  expected_value: Any = None):
        """Add a diagnostic issue to the report."""
        self.issues.append(DiagnosticIssue(
            severity=severity,
            category=category,
            description=description,
            location=location,
            recommendation=recommendation,
            actual_value=actual_value,
            expected_value=expected_value
        ))
    
    def run_all_checks(self) -> List[DiagnosticIssue]:
        """Run all diagnostic checks."""
        print("=" * 80)
        print("COMPREHENSIVE TRADING FLAW DIAGNOSTIC")
        print("=" * 80)
        print()
        
        self.check_profile_yaml_exists()
        self.check_profile_yaml_risk_limits()
        self.check_risk_envelope_defaults()
        self.check_profile_adapter_defaults()
        self.check_unified_sizing_consistency()
        self.check_agent_grid_configuration()
        self.check_window_based_risk_tracking()
        self.check_asset_coverage()
        self.check_legacy_vs_production()
        self.check_velocity_thresholds()
        self.check_price_caps()
        self.check_dynamic_sizing_disabled()
        self.check_order_gate_implementation()
        self.check_execution_gate()
        self.check_websocket_subscriptions()
        
        self.print_report()
        return self.issues
    
    def check_profile_yaml_exists(self):
        """Check if profile YAML exists and is readable."""
        print("Checking profile YAML existence...")
        profile_path = self.repo_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        if not profile_path.exists():
            self.add_issue(
                Severity.CRITICAL,
                "Configuration",
                "Profile YAML file does not exist",
                str(profile_path),
                "Create kalshi_crypto_15m_v2.yaml in config/profiles/ directory"
            )
            return
        
        try:
            import yaml
            with open(profile_path, 'r', encoding='utf-8') as f:
                self.profile_config = yaml.safe_load(f)
            print(f"  ✓ Profile YAML loaded successfully")
        except Exception as e:
            self.add_issue(
                Severity.CRITICAL,
                "Configuration",
                f"Failed to load profile YAML: {e}",
                str(profile_path),
                "Fix YAML syntax or file permissions"
            )
    
    def check_profile_yaml_risk_limits(self):
        """Check critical risk limits in profile YAML."""
        print("Checking profile YAML risk limits...")
        
        if not hasattr(self, 'profile_config'):
            return
        
        # Expected limits with their nested paths
        expected_limits = {
            ('guardrails_per_window_risk_pct',): 0.03,
            ('guardrails_total_venue_risk_pct',): 0.05,
            ('venue', 'max_total_notional_pct'): 0.15,
            ('kelly', 'kelly_hard_cap'): 0.02,
            ('kelly', 'kelly_global_notional_cap_pct'): 0.02,
            ('agent_defaults', 'max_notional_pct'): 0.03,
        }
        
        for key_path, expected in expected_limits.items():
            # Navigate nested dict
            value = self.profile_config
            for part in key_path:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break
            
            # If still dict, get 'value' key
            if isinstance(value, dict):
                value = value.get('value')
            
            key_str = '_'.join(key_path)
            if value is None:
                self.add_issue(
                    Severity.CRITICAL,
                    "Risk Configuration",
                    f"Missing risk limit: {key_str}",
                    "config/profiles/kalshi_crypto_15m_v2.yaml",
                    f"Add {key_str}: {expected} to profile YAML"
                )
            elif abs(value - expected) > 0.001:
                self.add_issue(
                    Severity.HIGH,
                    "Risk Configuration",
                    f"Risk limit mismatch: {key_str}",
                    "config/profiles/kalshi_crypto_15m_v2.yaml",
                    f"Set {key_str} to {expected}",
                    actual_value=value,
                    expected_value=expected
                )
            else:
                print(f"  ✓ {key_str}: {value}")
    
    def check_risk_envelope_defaults(self):
        """Check risk envelope defaults match profile YAML."""
        print("Checking risk envelope defaults...")
        
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
                compute_kalshi_crypto_15m_risk_envelope
            )
            
            # Try to compute envelope (may fail without bankroll)
            try:
                envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=100.0)
                
                # Check window limits
                if abs(envelope.guardrails_per_window_risk_pct - 0.03) > 0.001:
                    self.add_issue(
                        Severity.HIGH,
                        "Risk Envelope",
                        "Per-window risk limit mismatch",
                        "merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
                        "Set guardrails_per_window_risk_pct to 0.03",
                        actual_value=envelope.guardrails_per_window_risk_pct,
                        expected_value=0.03
                    )
                else:
                    print(f"  ✓ Per-window risk limit: {envelope.guardrails_per_window_risk_pct}")
                
                if abs(envelope.guardrails_total_venue_risk_pct - 0.05) > 0.001:
                    self.add_issue(
                        Severity.HIGH,
                        "Risk Envelope",
                        "Total venue window limit mismatch",
                        "merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
                        "Set guardrails_total_venue_risk_pct to 0.05",
                        actual_value=envelope.guardrails_total_venue_risk_pct,
                        expected_value=0.05
                    )
                else:
                    print(f"  ✓ Total venue window limit: {envelope.guardrails_total_venue_risk_pct}")
                
            except Exception as e:
                self.add_issue(
                    Severity.MEDIUM,
                    "Risk Envelope",
                    f"Risk envelope computation failed: {e}",
                    "merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
                    "Ensure profile YAML is valid and all required fields are present"
                )
                
        except ImportError as e:
            self.add_issue(
                Severity.CRITICAL,
                "Risk Envelope",
                f"Risk envelope module not importable: {e}",
                "merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
                "Fix import errors or missing dependencies"
            )
    
    def check_profile_adapter_defaults(self):
        """Check profile adapter defaults match profile YAML."""
        print("Checking profile adapter defaults...")
        
        try:
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
            
            adapter = Crypto15mProfileAdapter()
            profile = adapter._profile
            
            if profile is None:
                self.add_issue(
                    Severity.CRITICAL,
                    "Profile Adapter",
                    "Profile adapter failed to load profile",
                    "merid/risk/profiles/crypto_15m_profile.py",
                    "Check profile YAML path and loading logic"
                )
                return
            
            # Check critical defaults
            expected_defaults = {
                'agent_max_notional_pct': 0.03,
                'venue_max_total_notional_pct': 0.15,
                'guardrails_per_window_risk_pct': 0.03,
                'guardrails_total_venue_risk_pct': 0.05,
                'kelly_hard_cap': 0.02,
                'kelly_global_notional_cap_pct': 0.02,
            }
            
            for attr, expected in expected_defaults.items():
                if hasattr(profile, attr):
                    actual = getattr(profile, attr)
                    if abs(actual - expected) > 0.001:
                        self.add_issue(
                            Severity.HIGH,
                            "Profile Adapter",
                            f"Default mismatch: {attr}",
                            "merid/risk/profiles/crypto_15m_profile.py",
                            f"Set {attr} to {expected}",
                            actual_value=actual,
                            expected_value=expected
                        )
                    else:
                        print(f"  ✓ {attr}: {actual}")
                else:
                    self.add_issue(
                        Severity.HIGH,
                        "Profile Adapter",
                        f"Missing attribute: {attr}",
                        "merid/risk/profiles/crypto_15m_profile.py",
                        f"Add {attr} attribute to Crypto15mProfile dataclass"
                    )
                    
        except ImportError as e:
            self.add_issue(
                Severity.CRITICAL,
                "Profile Adapter",
                f"Profile adapter module not importable: {e}",
                "merid/risk/profiles/crypto_15m_profile.py",
                "Fix import errors or missing dependencies"
            )
    
    def check_unified_sizing_consistency(self):
        """Check unified sizing layer consistency with risk limits."""
        print("Checking unified sizing consistency...")
        
        try:
            from merid.prediction.unified_sizing import (
                _get_bankroll_cap_pct,
                _get_per_trade_risk_pct,
                _get_max_single_order_pct
            )
            
            # Check bankroll cap
            try:
                bankroll_cap = _get_bankroll_cap_pct()
                if abs(float(bankroll_cap) - 0.03) > 0.001:
                    self.add_issue(
                        Severity.HIGH,
                        "Unified Sizing",
                        "Bankroll cap percentage mismatch",
                        "merid/prediction/unified_sizing.py",
                        "Ensure bankroll_cap_pct reads 0.03 from profile",
                        actual_value=float(bankroll_cap),
                        expected_value=0.03
                    )
                else:
                    print(f"  ✓ Bankroll cap: {bankroll_cap}")
            except Exception as e:
                self.add_issue(
                    Severity.MEDIUM,
                    "Unified Sizing",
                    f"Bankroll cap check failed: {e}",
                    "merid/prediction/unified_sizing.py",
                    "Ensure profile is active and readable"
                )
            
            # Check per-trade risk
            try:
                per_trade_risk = _get_per_trade_risk_pct()
                if abs(float(per_trade_risk) - 0.03) > 0.001:
                    self.add_issue(
                        Severity.HIGH,
                        "Unified Sizing",
                        "Per-trade risk percentage mismatch",
                        "merid/prediction/unified_sizing.py",
                        "Ensure per_trade_risk_pct reads 0.03 from profile",
                        actual_value=float(per_trade_risk),
                        expected_value=0.03
                    )
                else:
                    print(f"  ✓ Per-trade risk: {per_trade_risk}")
            except Exception as e:
                self.add_issue(
                    Severity.MEDIUM,
                    "Unified Sizing",
                    f"Per-trade risk check failed: {e}",
                    "merid/prediction/unified_sizing.py",
                    "Ensure profile is active and readable"
                )
            
            # Check max single order
            try:
                max_single_order = _get_max_single_order_pct()
                if abs(float(max_single_order) - 0.03) > 0.001:
                    self.add_issue(
                        Severity.HIGH,
                        "Unified Sizing",
                        "Max single order percentage mismatch",
                        "merid/prediction/unified_sizing.py",
                        "Ensure max_single_order_pct reads 0.03 from profile",
                        actual_value=float(max_single_order),
                        expected_value=0.03
                    )
                else:
                    print(f"  ✓ Max single order: {max_single_order}")
            except Exception as e:
                self.add_issue(
                    Severity.MEDIUM,
                    "Unified Sizing",
                    f"Max single order check failed: {e}",
                    "merid/prediction/unified_sizing.py",
                    "Ensure profile is active and readable"
                )
                
        except ImportError as e:
            self.add_issue(
                Severity.CRITICAL,
                "Unified Sizing",
                f"Unified sizing module not importable: {e}",
                "merid/prediction/unified_sizing.py",
                "Fix import errors or missing dependencies"
            )
    
    def check_agent_grid_configuration(self):
        """Check agent grid configuration for asset coverage and thresholds."""
        print("Checking agent grid configuration...")
        
        try:
            from merid.prediction.agent_grid_15m import LeanAgentConfig
            
            # Check velocity thresholds
            expected_velocity = {
                'velocity_threshold_btc': 0.00015,
                'velocity_threshold_eth': 0.00015,
                'velocity_threshold_sol': 0.000225,
                'velocity_threshold_xrp': 0.000225,
                'velocity_threshold_doge': 0.0003,
            }
            
            for attr, expected in expected_velocity.items():
                # Check if default matches expected
                if hasattr(LeanAgentConfig, attr):
                    default_value = LeanAgentConfig.__dataclass_fields__[attr].default
                    if abs(default_value - expected) > 0.000001:
                        self.add_issue(
                            Severity.HIGH,
                            "Agent Grid",
                            f"Velocity threshold mismatch: {attr}",
                            "merid/prediction/agent_grid_15m.py",
                            f"Set {attr} to {expected}",
                            actual_value=default_value,
                            expected_value=expected
                        )
                    else:
                        print(f"  ✓ {attr}: {default_value}")
                else:
                    self.add_issue(
                        Severity.HIGH,
                        "Agent Grid",
                        f"Missing velocity threshold: {attr}",
                        "merid/prediction/agent_grid_15m.py",
                        f"Add {attr} to LeanAgentConfig"
                    )
            
            # Check max orders per 15m window
            if hasattr(LeanAgentConfig, 'max_orders_per_15m_window'):
                max_orders = LeanAgentConfig.__dataclass_fields__['max_orders_per_15m_window'].default
                # Profile YAML specifies 12 (not 5) - increased for more opportunities
                if max_orders != 12:
                    self.add_issue(
                        Severity.HIGH,
                        "Agent Grid",
                        "Max orders per 15m window mismatch",
                        "merid/prediction/agent_grid_15m.py",
                        "Set max_orders_per_15m_window to 12",
                        actual_value=max_orders,
                        expected_value=12
                    )
                else:
                    print(f"  ✓ Max orders per 15m window: {max_orders}")
                    
        except ImportError as e:
            self.add_issue(
                Severity.CRITICAL,
                "Agent Grid",
                f"Agent grid module not importable: {e}",
                "merid/prediction/agent_grid_15m.py",
                "Fix import errors or missing dependencies"
            )
    
    def check_window_based_risk_tracking(self):
        """Check window-based risk tracking implementation."""
        print("Checking window-based risk tracking...")
        
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
                KalshiCrypto15mRiskEnvelope,
                _WINDOW_TRACKING_STATE
            )
            
            # Check if window tracking state exists
            if not hasattr(_WINDOW_TRACKING_STATE, '__getitem__'):
                self.add_issue(
                    Severity.CRITICAL,
                    "Window Tracking",
                    "Window tracking state not properly initialized",
                    "merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
                    "Ensure _WINDOW_TRACKING_STATE is a dict with required keys"
                )
            else:
                required_keys = ['window_start_ts', 'agent_exposure_usd', 'total_exposure_usd']
                for key in required_keys:
                    if key not in _WINDOW_TRACKING_STATE:
                        self.add_issue(
                            Severity.CRITICAL,
                            "Window Tracking",
                            f"Missing window tracking key: {key}",
                            "merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
                            f"Add {key} to _WINDOW_TRACKING_STATE"
                        )
                print(f"  ✓ Window tracking state initialized")
            
            # Check if envelope has window limit methods
            envelope_methods = ['check_window_limit', 'record_order_execution', 'record_position_closure']
            for method in envelope_methods:
                if not hasattr(KalshiCrypto15mRiskEnvelope, method):
                    self.add_issue(
                        Severity.CRITICAL,
                        "Window Tracking",
                        f"Missing window tracking method: {method}",
                        "merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
                        f"Implement {method} in KalshiCrypto15mRiskEnvelope"
                    )
                else:
                    print(f"  ✓ Window tracking method: {method}")
                    
        except ImportError as e:
            self.add_issue(
                Severity.CRITICAL,
                "Window Tracking",
                f"Risk envelope module not importable: {e}",
                "merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
                "Fix import errors or missing dependencies"
            )
    
    def check_asset_coverage(self):
        """Check that all 5 crypto assets are covered."""
        print("Checking asset coverage...")
        
        required_assets = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']
        
        try:
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
            
            adapter = Crypto15mProfileAdapter()
            profile = adapter._profile
            
            if profile is None:
                self.add_issue(
                    Severity.CRITICAL,
                    "Asset Coverage",
                    "Profile not loaded, cannot check asset coverage",
                    "merid/risk/profiles/crypto_15m_profile.py",
                    "Fix profile loading"
                )
                return
            
            # Check asset configs
            for asset in required_assets:
                if asset not in profile.asset_configs:
                    self.add_issue(
                        Severity.CRITICAL,
                        "Asset Coverage",
                        f"Missing asset configuration: {asset}",
                        "config/profiles/kalshi_crypto_15m_v2.yaml",
                        f"Add {asset} configuration to assets section"
                    )
                else:
                    print(f"  ✓ Asset configured: {asset}")
                    
        except ImportError as e:
            self.add_issue(
                Severity.CRITICAL,
                "Asset Coverage",
                f"Profile adapter module not importable: {e}",
                "merid/risk/profiles/crypto_15m_profile.py",
                "Fix import errors or missing dependencies"
            )
    
    def check_legacy_vs_production(self):
        """Check for legacy vs production contamination."""
        print("Checking legacy vs production contamination...")
        
        # Check if main.py exists (legacy)
        main_py = self.repo_root / "web" / "main.py"
        main_15m_lean = self.repo_root / "web" / "main_15m_lean.py"
        
        if main_py.exists():
            self.add_issue(
                Severity.HIGH,
                "Legacy Contamination",
                "Legacy main.py exists - may cause contamination",
                "web/main.py",
                "Ensure production uses main_15m_lean.py exclusively, consider removing or renaming main.py"
            )
        
        if not main_15m_lean.exists():
            self.add_issue(
                Severity.CRITICAL,
                "Legacy Contamination",
                "Production main_15m_lean.py does not exist",
                "web/main_15m_lean.py",
                "Ensure main_15m_lean.py exists for 15m production stack"
            )
        else:
            print(f"  ✓ Production main_15m_lean.py exists")
        
        # Check for imports of legacy modules
        legacy_patterns = [
            'from web.main import',
            'from web.main import',
            'import web.main',
        ]
        
        # Check key files for legacy imports
        files_to_check = [
            self.repo_root / "web" / "main_15m_lean.py",
            self.repo_root / "merid" / "loop_15m.py",
        ]
        
        for file_path in files_to_check:
            if file_path.exists():
                try:
                    with open(file_path, 'r') as f:
                        content = f.read()
                    for pattern in legacy_patterns:
                        if pattern in content:
                            self.add_issue(
                                Severity.HIGH,
                                "Legacy Contamination",
                                f"Legacy import found: {pattern}",
                                str(file_path),
                                f"Remove legacy import and use production modules"
                            )
                except Exception:
                    pass
    
    def check_velocity_thresholds(self):
        """Check velocity thresholds are aligned across all layers."""
        print("Checking velocity threshold alignment...")
        
        expected_thresholds = {
            'BTC': 0.00015,
            'ETH': 0.00015,
            'SOL': 0.000225,
            'XRP': 0.000225,
            'DOGE': 0.0003,
        }
        
        # Check profile YAML (velocity_thresholds section, not velocity_model.coefficients)
        if hasattr(self, 'profile_config'):
            velocity_thresholds = self.profile_config.get('velocity_thresholds', {})
            
            for asset, expected in expected_thresholds.items():
                if asset in velocity_thresholds:
                    actual = velocity_thresholds[asset]
                    if abs(actual - expected) > 0.000001:
                        self.add_issue(
                            Severity.HIGH,
                            "Velocity Thresholds",
                            f"Velocity threshold mismatch in profile: {asset}",
                            "config/profiles/kalshi_crypto_15m_v2.yaml",
                            f"Set velocity_thresholds.{asset} to {expected}",
                            actual_value=actual,
                            expected_value=expected
                        )
                    else:
                        print(f"  ✓ {asset} velocity threshold (profile): {actual}")
                else:
                    self.add_issue(
                        Severity.HIGH,
                        "Velocity Thresholds",
                        f"Missing velocity threshold in profile: {asset}",
                        "config/profiles/kalshi_crypto_15m_v2.yaml",
                        f"Add {asset}: {expected} to velocity_thresholds section"
                    )
    
    def check_price_caps(self):
        """Check price caps are correctly configured."""
        print("Checking price caps...")
        
        # Check 75c threshold
        try:
            from merid.event_venues.kalshi.risk_parameters import DEEP_OTM_EXPENSIVE_CENTS
            
            if DEEP_OTM_EXPENSIVE_CENTS != 75:
                self.add_issue(
                    Severity.HIGH,
                    "Price Caps",
                    f"DEEP_OTM_EXPENSIVE_CENTS is {DEEP_OTM_EXPENSIVE_CENTS}, expected 75",
                    "merid/event_venues/kalshi/risk_parameters.py",
                    "Set DEEP_OTM_EXPENSIVE_CENTS to 75",
                    actual_value=DEEP_OTM_EXPENSIVE_CENTS,
                    expected_value=75
                )
            else:
                print(f"  ✓ DEEP_OTM_EXPENSIVE_CENTS: {DEEP_OTM_EXPENSIVE_CENTS}")
                
        except ImportError:
            self.add_issue(
                Severity.MEDIUM,
                "Price Caps",
                "risk_parameters module not importable",
                "merid/event_venues/kalshi/risk_parameters.py",
                "Fix import errors"
            )
        
        # Check hybrid mode price caps in profile
        if hasattr(self, 'profile_config'):
            hybrid = self.profile_config.get('hybrid', {})
            max_yes = hybrid.get('max_entry_price_yes')
            min_no = hybrid.get('min_entry_price_no')
            
            if max_yes is not None and abs(max_yes - 0.70) > 0.01:
                self.add_issue(
                    Severity.HIGH,
                    "Price Caps",
                    f"Hybrid max_entry_price_yes is {max_yes}, expected 0.70",
                    "config/profiles/kalshi_crypto_15m_v2.yaml",
                    "Set hybrid.max_entry_price_yes to 0.70",
                    actual_value=max_yes,
                    expected_value=0.70
                )
            else:
                print(f"  ✓ Hybrid max_entry_price_yes: {max_yes}")
            
            if min_no is not None and abs(min_no - 0.30) > 0.01:
                self.add_issue(
                    Severity.HIGH,
                    "Price Caps",
                    f"Hybrid min_entry_price_no is {min_no}, expected 0.30",
                    "config/profiles/kalshi_crypto_15m_v2.yaml",
                    "Set hybrid.min_entry_price_no to 0.30",
                    actual_value=min_no,
                    expected_value=0.30
                )
            else:
                print(f"  ✓ Hybrid min_entry_price_no: {min_no}")
    
    def check_dynamic_sizing_disabled(self):
        """Check that dynamic sizing multipliers are disabled to prevent interference with risk limits."""
        print("Checking dynamic sizing disabled...")
        
        try:
            from merid.prediction.unified_sizing import (
                _get_regime_position_size_multiplier,
                _get_tte_position_size_multiplier
            )
            
            # Check regime sizing
            regime_multiplier = _get_regime_position_size_multiplier()
            if regime_multiplier != 1.0:
                self.add_issue(
                    Severity.HIGH,
                    "Dynamic Sizing",
                    f"Regime sizing multiplier is {regime_multiplier}, expected 1.0 (disabled)",
                    "merid/prediction/unified_sizing.py",
                "Ensure _get_regime_position_size_multiplier returns 1.0",
                    actual_value=regime_multiplier,
                    expected_value=1.0
                )
            else:
                print(f"  ✓ Regime sizing disabled (multiplier=1.0)")
            
            # Check TTE sizing
            tte_multiplier = _get_tte_position_size_multiplier()
            if tte_multiplier != 1.0:
                self.add_issue(
                    Severity.HIGH,
                    "Dynamic Sizing",
                    f"TTE sizing multiplier is {tte_multiplier}, expected 1.0 (disabled)",
                    "merid/prediction/unified_sizing.py",
                    "Ensure _get_tte_position_size_multiplier returns 1.0",
                    actual_value=tte_multiplier,
                    expected_value=1.0
                )
            else:
                print(f"  ✓ TTE sizing disabled (multiplier=1.0)")
            
            # Check profile YAML dynamic_sizing.enabled
            if hasattr(self, 'profile_config'):
                dynamic_sizing = self.profile_config.get('dynamic_sizing', {})
                enabled = dynamic_sizing.get('enabled')
                
                if enabled is True:
                    self.add_issue(
                        Severity.HIGH,
                        "Dynamic Sizing",
                        "Dynamic sizing is enabled in profile YAML",
                        "config/profiles/kalshi_crypto_15m_v2.yaml",
                        "Set dynamic_sizing.enabled to false to prevent interference with risk limits",
                        actual_value=enabled,
                        expected_value=False
                    )
                else:
                    print(f"  ✓ Dynamic sizing disabled in profile YAML")
                    
        except ImportError as e:
            self.add_issue(
                Severity.MEDIUM,
                "Dynamic Sizing",
                f"Unified sizing module not importable: {e}",
                "merid/prediction/unified_sizing.py",
                "Fix import errors"
            )
    
    def check_order_gate_implementation(self):
        """Check order gate implementation for window limit enforcement."""
        print("Checking order gate implementation...")
        
        try:
            from merid.event_venues.kalshi.order_gate import GateMetrics, PreTradeGate
            
            # Check if window limit counter exists
            if hasattr(GateMetrics, 'blocked_window_limit'):
                print(f"  ✓ Order gate has window limit counter")
            else:
                self.add_issue(
                    Severity.HIGH,
                    "Order Gate",
                    "Order gate missing window limit counter",
                    "merid/event_venues/kalshi/order_gate.py",
                    "Add blocked_window_limit to GateMetrics"
                )
            
            # Check if PreTradeGate has check method
            if hasattr(PreTradeGate, 'check'):
                print(f"  ✓ Order gate has check method")
            else:
                self.add_issue(
                    Severity.CRITICAL,
                    "Order Gate",
                    "Order gate missing check method",
                    "merid/event_venues/kalshi/order_gate.py",
                    "Implement check method in PreTradeGate"
                )
                
        except ImportError as e:
            self.add_issue(
                Severity.CRITICAL,
                "Order Gate",
                f"Order gate module not importable: {e}",
                "merid/event_venues/kalshi/order_gate.py",
                "Fix import errors or missing dependencies"
            )
    
    def check_execution_gate(self):
        """Check execution gate for kill switch and other blocking conditions."""
        print("Checking execution gate...")
        
        try:
            from core.execution_gate import check_execution_gate, GateState
            
            # Try to check gate status
            try:
                status = check_execution_gate()
                
                if status.blocked:
                    self.add_issue(
                        Severity.CRITICAL,
                        "Execution Gate",
                        f"Execution gate is BLOCKED: {[r.source for r in status.reasons]}",
                        "core/execution_gate.py",
                        "Investigate and resolve blocking conditions (kill switch, reconciliation, etc.)"
                    )
                elif status.is_limited:
                    self.add_issue(
                        Severity.HIGH,
                        "Execution Gate",
                        f"Execution gate is LIMITED: {[r.source for r in status.reasons]}",
                        "core/execution_gate.py",
                        "Investigate warning conditions"
                    )
                else:
                    print(f"  ✓ Execution gate is CLEAR")
                    
            except Exception as e:
                self.add_issue(
                    Severity.MEDIUM,
                    "Execution Gate",
                    f"Execution gate check failed: {e}",
                    "core/execution_gate.py",
                    "Ensure all gate dependencies are available"
                )
                
        except ImportError as e:
            self.add_issue(
                Severity.CRITICAL,
                "Execution Gate",
                f"Execution gate module not importable: {e}",
                "core/execution_gate.py",
                "Fix import errors or missing dependencies"
            )
    
    def check_websocket_subscriptions(self):
        """Check WebSocket subscription setup."""
        print("Checking WebSocket subscriptions...")
        
        # Check for WebSocket bridge (production implementation)
        ws_bridge = self.repo_root / "merid" / "event_venues" / "kalshi" / "ws_bridge.py"
        if not ws_bridge.exists():
            self.add_issue(
                Severity.MEDIUM,
                "WebSocket",
                "WebSocket bridge not found",
                "merid/event_venues/kalshi/ws_bridge.py",
                "Ensure ws_bridge.py is implemented for market data"
            )
        else:
            print(f"  ✓ WebSocket bridge found: ws_bridge.py")
        
        # Check for market state (correct file name is market_state.py, not market_state_store.py)
        try:
            from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
            print(f"  ✓ Market state store available (market_state.py)")
        except ImportError:
            self.add_issue(
                Severity.HIGH,
                "WebSocket",
                "Market state store not importable",
                "merid/event_venues/kalshi/market_state.py",
                "Fix import errors or missing dependencies"
            )
    
    def print_report(self):
        """Print the diagnostic report."""
        print()
        print("=" * 80)
        print("DIAGNOSTIC REPORT")
        print("=" * 80)
        print()
        
        # Group by severity
        by_severity = {
            Severity.CRITICAL: [],
            Severity.HIGH: [],
            Severity.MEDIUM: [],
            Severity.LOW: [],
        }
        
        for issue in self.issues:
            by_severity[issue.severity].append(issue)
        
        # Print issues by severity
        for severity in [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]:
            issues = by_severity[severity]
            if issues:
                print(f"{severity.value} ISSUES ({len(issues)})")
                print("-" * 80)
                for i, issue in enumerate(issues, 1):
                    print(f"\n{i}. {issue.category}: {issue.description}")
                    print(f"   Location: {issue.location}")
                    print(f"   Recommendation: {issue.recommendation}")
                    if issue.actual_value is not None and issue.expected_value is not None:
                        print(f"   Actual: {issue.actual_value}, Expected: {issue.expected_value}")
                print()
        
        # Summary
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Total Issues: {len(self.issues)}")
        print(f"  CRITICAL: {len(by_severity[Severity.CRITICAL])}")
        print(f"  HIGH: {len(by_severity[Severity.HIGH])}")
        print(f"  MEDIUM: {len(by_severity[Severity.MEDIUM])}")
        print(f"  LOW: {len(by_severity[Severity.LOW])}")
        print()
        
        if by_severity[Severity.CRITICAL]:
            print("⚠️  CRITICAL issues found - trading execution may be BLOCKED")
        elif by_severity[Severity.HIGH]:
            print("⚠️  HIGH severity issues found - trading execution may be DEGRADED")
        elif by_severity[Severity.MEDIUM]:
            print("⚠️  MEDIUM severity issues found - review recommended")
        else:
            print("✓ No critical or high severity issues found")
        print()


def main():
    """Run the comprehensive diagnostic."""
    diagnostic = TradingFlawDiagnostic()
    issues = diagnostic.run_all_checks()
    
    # Exit with error code if critical issues found
    critical_count = sum(1 for i in issues if i.severity == Severity.CRITICAL)
    if critical_count > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
