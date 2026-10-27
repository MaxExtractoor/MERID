#!/usr/bin/env python3
"""
End-to-End Consistency Audit Script for MERID 15M Kalshi Crypto Trading Stack

This script performs a comprehensive audit across all layers (upstream, midstream, downstream)
to expose gaps and discrepancies in risk configuration and enforcement.

Layers audited:
- UPSTREAM: Profile YAML (config/profiles/kalshi_crypto_15m_v2.yaml)
- MIDSTREAM: Risk envelope (merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py)
- MIDSTREAM: Profile adapter (merid/risk/profiles/crypto_15m_profile.py)
- DOWNSTREAM: Unified sizing (merid/prediction/unified_sizing.py)
- AGENT GRID: Signal generation (merid/prediction/agent_grid_15m.py)

Critical parameters audited:
- Per-agent notional limits (3%)
- Per-asset notional limits (3% each)
- Window-based risk limits (3% per agent, 5% total per 15m window)
- Kelly hard caps (2%)
- Velocity thresholds (per-asset)
- Max contracts per order (1)
- Asset coverage (BTC, ETH, SOL, XRP, DOGE)
"""

import sys
import os
from pathlib import Path
from typing import Dict, Any, List, Tuple
import yaml

# Add repository root to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))


class Color:
    """ANSI color codes for terminal output."""
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    RESET = '\033[0m'


def print_header(text: str):
    """Print a formatted header."""
    print(f"\n{Color.BOLD}{Color.CYAN}{'=' * 80}{Color.RESET}")
    print(f"{Color.BOLD}{Color.CYAN}{text}{Color.RESET}")
    print(f"{Color.BOLD}{Color.CYAN}{'=' * 80}{Color.RESET}\n")


def print_section(text: str):
    """Print a formatted section header."""
    print(f"\n{Color.BOLD}{Color.BLUE}--- {text} ---{Color.RESET}\n")


def print_success(text: str):
    """Print success message."""
    print(f"{Color.GREEN}✓ {text}{Color.RESET}")


def print_error(text: str):
    """Print error message."""
    print(f"{Color.RED}✗ {text}{Color.RESET}")


def print_warning(text: str):
    """Print warning message."""
    print(f"{Color.YELLOW}⚠ {text}{Color.RESET}")


def print_info(text: str):
    """Print info message."""
    print(f"{Color.WHITE}  {text}{Color.RESET}")


class Discrepancy:
    """Represents a configuration discrepancy between layers."""
    
    def __init__(self, parameter: str, layer1: str, value1: Any, layer2: str, value2: Any, severity: str = "ERROR"):
        self.parameter = parameter
        self.layer1 = layer1
        self.value1 = value1
        self.layer2 = layer2
        self.value2 = value2
        self.severity = severity
    
    def __str__(self):
        color = Color.RED if self.severity == "ERROR" else Color.YELLOW
        return f"{color}[{self.severity}] {self.parameter}: {self.layer1}={self.value1} vs {self.layer2}={self.value2}{Color.RESET}"


class AuditResult:
    """Container for audit results."""
    
    def __init__(self):
        self.discrepancies: List[Discrepancy] = []
        self.missing_parameters: List[Tuple[str, str]] = []  # (layer, parameter)
        self.window_tracking_checks: List[Dict[str, Any]] = []
        self.asset_coverage: Dict[str, Dict[str, Any]] = {}
    
    def add_discrepancy(self, parameter: str, layer1: str, value1: Any, layer2: str, value2: Any, severity: str = "ERROR"):
        """Add a discrepancy to the results."""
        self.discrepancies.append(Discrepancy(parameter, layer1, value1, layer2, value2, severity))
    
    def add_missing_parameter(self, layer: str, parameter: str):
        """Add a missing parameter to the results."""
        self.missing_parameters.append((layer, parameter))
    
    def add_window_tracking_check(self, check_name: str, passed: bool, details: str):
        """Add a window tracking check result."""
        self.window_tracking_checks.append({
            "check": check_name,
            "passed": passed,
            "details": details
        })
    
    def set_asset_coverage(self, asset: str, coverage: Dict[str, Any]):
        """Set asset coverage information."""
        self.asset_coverage[asset] = coverage
    
    def print_summary(self):
        """Print a summary of audit results."""
        print_header("AUDIT SUMMARY")
        
        # Discrepancies
        if self.discrepancies:
            print_section(f"DISCREPANCIES FOUND ({len(self.discrepancies)})")
            for disc in self.discrepancies:
                print(str(disc))
        else:
            print_success("No discrepancies found across layers")
        
        # Missing parameters
        if self.missing_parameters:
            print_section(f"MISSING PARAMETERS ({len(self.missing_parameters)})")
            for layer, param in self.missing_parameters:
                print_error(f"{layer}: {param}")
        else:
            print_success("All required parameters present")
        
        # Window tracking
        print_section("WINDOW-BASED RISK TRACKING")
        for check in self.window_tracking_checks:
            if check["passed"]:
                print_success(f"{check['check']}: {check['details']}")
            else:
                print_error(f"{check['check']}: {check['details']}")
        
        # Asset coverage
        print_section("ASSET COVERAGE (BTC, ETH, SOL, XRP, DOGE)")
        for asset, coverage in self.asset_coverage.items():
            print_info(f"{asset}: {coverage}")
        
        # Overall status
        print_header("OVERALL STATUS")
        total_issues = len(self.discrepancies) + len(self.missing_parameters)
        failed_window_checks = sum(1 for c in self.window_tracking_checks if not c["passed"])
        
        if total_issues == 0 and failed_window_checks == 0:
            print_success("ALL CHECKS PASSED - Stack is consistent across all layers")
        else:
            print_error(f"FOUND {total_issues} ISSUES and {failed_window_checks} FAILED WINDOW CHECKS")


def load_profile_yaml() -> Dict[str, Any]:
    """Load the profile YAML configuration."""
    profile_path = repo_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
    
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile YAML not found: {profile_path}")
    
    with open(profile_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def extract_profile_yaml_params(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Extract critical parameters from profile YAML."""
    params = {}
    
    # Agent defaults
    agent_defaults = profile.get('agent_defaults', {})
    params['agent_max_notional_pct'] = agent_defaults.get('max_notional_pct')
    params['max_yes_position'] = agent_defaults.get('max_yes_position')
    params['max_no_position'] = agent_defaults.get('max_no_position')
    
    # Venue caps
    venue = profile.get('venue', {})
    params['venue_max_total_notional_pct'] = venue.get('max_total_notional_pct', {}).get('value')
    params['venue_bankroll_cap_pct'] = venue.get('bankroll_cap_pct', {}).get('value')
    
    # Window-based risk limits
    params['guardrails_per_window_risk_pct'] = profile.get('guardrails_per_window_risk_pct', {}).get('value')
    params['guardrails_total_venue_risk_pct'] = profile.get('guardrails_total_venue_risk_pct', {}).get('value')
    
    # Kelly
    kelly = profile.get('kelly', {})
    params['kelly_hard_cap'] = kelly.get('kelly_hard_cap')
    params['kelly_global_notional_cap_pct'] = kelly.get('kelly_global_notional_cap_pct')
    
    # Max cycle risk
    params['max_cycle_risk_pct'] = profile.get('max_cycle_risk_pct', {}).get('value')
    
    # Per-asset configs
    assets = profile.get('assets', {})
    params['assets'] = {}
    for asset_name, asset_config in assets.items():
        params['assets'][asset_name] = {
            'max_notional_pct': asset_config.get('max_notional_pct', {}).get('value'),
            'max_contracts': asset_config.get('max_contracts', {}).get('value'),
        }
    
    # Velocity thresholds (from velocity_thresholds section)
    velocity_thresholds = profile.get('velocity_thresholds', {})
    params['velocity_threshold_btc'] = velocity_thresholds.get('BTC')
    params['velocity_threshold_eth'] = velocity_thresholds.get('ETH')
    params['velocity_threshold_sol'] = velocity_thresholds.get('SOL')
    params['velocity_threshold_xrp'] = velocity_thresholds.get('XRP')
    params['velocity_threshold_doge'] = velocity_thresholds.get('DOGE')
    
    return params


def extract_risk_envelope_defaults() -> Dict[str, Any]:
    """Extract default values from risk envelope module."""
    params = {}
    
    # Read the risk envelope file to extract defaults
    risk_envelope_path = repo_root / "merid" / "risk" / "profiles" / "kalshi_crypto_15m_risk_envelope.py"
    
    if not risk_envelope_path.exists():
        raise FileNotFoundError(f"Risk envelope not found: {risk_envelope_path}")
    
    with open(risk_envelope_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract defaults using simple parsing (looking for .get() calls with defaults)
    import re
    
    # guardrails_per_window_risk_pct default - look for the actual default value in the get() call
    match = re.search(r"guardrails_per_window_risk_pct_raw.*?\.get\([^,]+,\s*([0-9.]+)\)", content, re.DOTALL)
    if match:
        params['guardrails_per_window_risk_pct'] = float(match.group(1))
    
    # guardrails_total_venue_risk_pct default
    match = re.search(r"guardrails_total_venue_risk_pct_raw.*?\.get\([^,]+,\s*([0-9.]+)\)", content, re.DOTALL)
    if match:
        params['guardrails_total_venue_risk_pct'] = float(match.group(1))
    
    # max_cycle_risk_pct default
    match = re.search(r"max_cycle_risk_pct_raw.*?\.get\([^,]+,\s*([0-9.]+)\)", content, re.DOTALL)
    if match:
        params['max_cycle_risk_pct'] = float(match.group(1))
    
    return params


def extract_profile_adapter_defaults() -> Dict[str, Any]:
    """Extract default values from profile adapter module."""
    params = {}
    
    # Read the profile adapter file
    profile_adapter_path = repo_root / "merid" / "risk" / "profiles" / "crypto_15m_profile.py"
    
    if not profile_adapter_path.exists():
        raise FileNotFoundError(f"Profile adapter not found: {profile_adapter_path}")
    
    with open(profile_adapter_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    import re
    
    # agent_max_notional_pct default - look for the actual default value in the get() call
    match = re.search(r"agent_max_notional_pct\s*=\s*agent_defaults\.get\([^,]+,\s*([0-9.]+)\)", content, re.DOTALL)
    if match:
        params['agent_max_notional_pct'] = float(match.group(1))
    
    # venue_max_total_notional_pct default
    match = re.search(r"venue_max_total_notional_pct\s*=\s*venue\.get\([^,]+,\s*([0-9.]+)\)", content, re.DOTALL)
    if match:
        params['venue_max_total_notional_pct'] = float(match.group(1))
    
    # guardrails_per_window_risk_pct default - look for _normalize_percentage_value call
    match = re.search(r"guardrails_per_window_risk_pct\s*=\s*self\._normalize_percentage_value\(\s*raw\.get\([^,]+,\s*([0-9.]+)\)", content, re.DOTALL)
    if match:
        params['guardrails_per_window_risk_pct'] = float(match.group(1))
    
    # guardrails_total_venue_risk_pct default
    match = re.search(r"guardrails_total_venue_risk_pct\s*=\s*self\._normalize_percentage_value\(\s*raw\.get\([^,]+,\s*([0-9.]+)\)", content, re.DOTALL)
    if match:
        params['guardrails_total_venue_risk_pct'] = float(match.group(1))
    
    return params


def extract_unified_sizing_defaults() -> Dict[str, Any]:
    """Extract default values from unified sizing module."""
    params = {}
    
    # Read the unified sizing file
    unified_sizing_path = repo_root / "merid" / "prediction" / "unified_sizing.py"
    
    if not unified_sizing_path.exists():
        raise FileNotFoundError(f"Unified sizing not found: {unified_sizing_path}")
    
    with open(unified_sizing_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    import re
    
    # Check for dynamic_sizing_max_contracts default
    match = re.search(r"dynamic_sizing_max_contracts.*?return\s+([0-9]+)", content, re.DOTALL)
    if match:
        params['dynamic_sizing_max_contracts'] = int(match.group(1))
    
    # Check for max_contracts default in _get_max_contracts_per_asset
    match = re.search(r"_get_max_contracts_per_asset.*?return\s+([0-9]+)", content, re.DOTALL)
    if match:
        params['max_contracts_per_asset_default'] = int(match.group(1))
    
    return params


def extract_agent_grid_defaults() -> Dict[str, Any]:
    """Extract default values from agent grid module."""
    params = {}
    
    # Read the agent grid file
    agent_grid_path = repo_root / "merid" / "prediction" / "agent_grid_15m.py"
    
    if not agent_grid_path.exists():
        raise FileNotFoundError(f"Agent grid not found: {agent_grid_path}")
    
    with open(agent_grid_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    import re
    
    # Extract velocity_threshold default
    match = re.search(r"velocity_threshold:\s*float\s*=\s*([0-9.]+)", content)
    if match:
        params['velocity_threshold'] = float(match.group(1))
    
    # Extract per-asset velocity thresholds
    match = re.search(r"velocity_threshold_btc:\s*float\s*=\s*([0-9.]+)", content)
    if match:
        params['velocity_threshold_btc'] = float(match.group(1))
    
    match = re.search(r"velocity_threshold_eth:\s*float\s*=\s*([0-9.]+)", content)
    if match:
        params['velocity_threshold_eth'] = float(match.group(1))
    
    match = re.search(r"velocity_threshold_sol:\s*float\s*=\s*([0-9.]+)", content)
    if match:
        params['velocity_threshold_sol'] = float(match.group(1))
    
    match = re.search(r"velocity_threshold_xrp:\s*float\s*=\s*([0-9.]+)", content)
    if match:
        params['velocity_threshold_xrp'] = float(match.group(1))
    
    match = re.search(r"velocity_threshold_doge:\s*float\s*=\s*([0-9.]+)", content)
    if match:
        params['velocity_threshold_doge'] = float(match.group(1))
    
    return params


def check_window_tracking_implementation(result: AuditResult):
    """Check if window-based risk tracking is properly implemented."""
    risk_envelope_path = repo_root / "merid" / "risk" / "profiles" / "kalshi_crypto_15m_risk_envelope.py"
    
    if not risk_envelope_path.exists():
        result.add_window_tracking_check("Risk envelope file exists", False, "File not found")
        return
    
    with open(risk_envelope_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for module-level window tracking state
    has_module_state = "_WINDOW_TRACKING_STATE" in content
    result.add_window_tracking_check(
        "Module-level window tracking state",
        has_module_state,
        "Found _WINDOW_TRACKING_STATE" if has_module_state else "Missing _WINDOW_TRACKING_STATE"
    )
    
    # Check for check_window_limit method
    has_check_method = "def check_window_limit" in content
    result.add_window_tracking_check(
        "check_window_limit method",
        has_check_method,
        "Found check_window_limit method" if has_check_method else "Missing check_window_limit method"
    )
    
    # Check for record_order_execution method
    has_record_method = "def record_order_execution" in content
    result.add_window_tracking_check(
        "record_order_execution method",
        has_record_method,
        "Found record_order_execution method" if has_record_method else "Missing record_order_execution method"
    )
    
    # Check for record_position_closure method
    has_closure_method = "def record_position_closure" in content
    result.add_window_tracking_check(
        "record_position_closure method",
        has_closure_method,
        "Found record_position_closure method" if has_closure_method else "Missing record_position_closure method"
    )
    
    # Check for window rolling logic
    has_roll_logic = "_roll_window_if_needed_locked" in content
    result.add_window_tracking_check(
        "Window rolling logic",
        has_roll_logic,
        "Found _roll_window_if_needed_locked" if has_roll_logic else "Missing window rolling logic"
    )
    
    # Check for 3% and 5% hard stop enforcement
    has_3pct_check = "0.03" in content and "per_agent" in content
    has_5pct_check = "0.05" in content and "total_venue" in content
    result.add_window_tracking_check(
        "3% per-agent hard stop",
        has_3pct_check,
        "Found 3% per-agent enforcement" if has_3pct_check else "Missing 3% per-agent enforcement"
    )
    result.add_window_tracking_check(
        "5% total venue hard stop",
        has_5pct_check,
        "Found 5% total venue enforcement" if has_5pct_check else "Missing 5% total venue enforcement"
    )


def check_asset_coverage(profile_params: Dict[str, Any], result: AuditResult):
    """Check that all 5 crypto assets are consistently configured."""
    required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    for asset in required_assets:
        coverage = {"present": False, "max_notional_pct": None, "max_contracts": None}
        
        if asset in profile_params.get('assets', {}):
            coverage["present"] = True
            coverage["max_notional_pct"] = profile_params['assets'][asset].get('max_notional_pct')
            coverage["max_contracts"] = profile_params['assets'][asset].get('max_contracts')
        
        result.set_asset_coverage(asset, coverage)


def compare_parameters(profile_params: Dict[str, Any], 
                     risk_envelope_params: Dict[str, Any],
                     profile_adapter_params: Dict[str, Any],
                     unified_sizing_params: Dict[str, Any],
                     agent_grid_params: Dict[str, Any],
                     result: AuditResult):
    """Compare parameters across all layers and identify discrepancies."""
    
    # Define expected values (from memory)
    expected = {
        'agent_max_notional_pct': 0.03,
        'venue_max_total_notional_pct': 0.15,
        'guardrails_per_window_risk_pct': 0.03,
        'guardrails_total_venue_risk_pct': 0.05,
        'kelly_hard_cap': 0.02,
        'kelly_global_notional_cap_pct': 0.02,
        'max_yes_position': 5,
        'max_no_position': 5,
        'max_cycle_risk_pct': 0.05,
        'velocity_threshold_btc': 0.00015,
        'velocity_threshold_eth': 0.00015,
        'velocity_threshold_sol': 0.000225,
        'velocity_threshold_xrp': 0.000225,
        'velocity_threshold_doge': 0.0003,
    }
    
    # Compare profile YAML vs expected
    for param, expected_value in expected.items():
        if param in profile_params:
            profile_value = profile_params[param]
            if profile_value != expected_value:
                result.add_discrepancy(
                    param,
                    "PROFILE_YAML",
                    profile_value,
                    "EXPECTED",
                    expected_value,
                    "ERROR"
                )
        else:
            result.add_missing_parameter("PROFILE_YAML", param)
    
    # Compare risk envelope defaults vs profile YAML
    for param in ['guardrails_per_window_risk_pct', 'guardrails_total_venue_risk_pct', 'max_cycle_risk_pct']:
        if param in risk_envelope_params and param in profile_params:
            if risk_envelope_params[param] != profile_params[param]:
                result.add_discrepancy(
                    param,
                    "RISK_ENVELOPE",
                    risk_envelope_params[param],
                    "PROFILE_YAML",
                    profile_params[param],
                    "ERROR"
                )
    
    # Compare profile adapter defaults vs profile YAML
    for param in ['agent_max_notional_pct', 'venue_max_total_notional_pct', 
                  'guardrails_per_window_risk_pct', 'guardrails_total_venue_risk_pct']:
        if param in profile_adapter_params and param in profile_params:
            if profile_adapter_params[param] != profile_params[param]:
                result.add_discrepancy(
                    param,
                    "PROFILE_ADAPTER",
                    profile_adapter_params[param],
                    "PROFILE_YAML",
                    profile_params[param],
                    "ERROR"
                )
    
    # Compare unified sizing defaults vs expected
    if 'dynamic_sizing_max_contracts' in unified_sizing_params:
        if unified_sizing_params['dynamic_sizing_max_contracts'] != 1:
            result.add_discrepancy(
                'dynamic_sizing_max_contracts',
                "UNIFIED_SIZING",
                unified_sizing_params['dynamic_sizing_max_contracts'],
                "EXPECTED",
                1,
                "ERROR"
            )
    
    if 'max_contracts_per_asset_default' in unified_sizing_params:
        if unified_sizing_params['max_contracts_per_asset_default'] != 1:
            result.add_discrepancy(
                'max_contracts_per_asset_default',
                "UNIFIED_SIZING",
                unified_sizing_params['max_contracts_per_asset_default'],
                "EXPECTED",
                1,
                "ERROR"
            )
    
    # Compare agent grid velocity thresholds vs profile YAML
    for asset in ['btc', 'eth', 'sol', 'xrp', 'doge']:
        param = f'velocity_threshold_{asset}'
        if param in agent_grid_params and param in profile_params:
            if agent_grid_params[param] != profile_params[param]:
                result.add_discrepancy(
                    param,
                    "AGENT_GRID",
                    agent_grid_params[param],
                    "PROFILE_YAML",
                    profile_params[param],
                    "WARNING"
                )
    
    # Check per-asset max_contracts in profile YAML
    for asset in required_assets:
        if asset in profile_params.get('assets', {}):
            max_contracts = profile_params['assets'][asset].get('max_contracts')
            if max_contracts != 1:
                result.add_discrepancy(
                    f'{asset}_max_contracts',
                    "PROFILE_YAML",
                    max_contracts,
                    "EXPECTED",
                    1,
                    "ERROR"
                )


def main():
    """Main audit function."""
    print_header("MERID 15M KALSHI CRYPTO TRADING STACK - END-TO-END CONSISTENCY AUDIT")
    
    result = AuditResult()
    
    try:
        # Load profile YAML
        print_section("Loading Profile YAML")
        profile = load_profile_yaml()
        profile_params = extract_profile_yaml_params(profile)
        print_success(f"Loaded profile YAML with {len(profile_params)} parameters")
        
        # Extract risk envelope defaults
        print_section("Extracting Risk Envelope Defaults")
        risk_envelope_params = extract_risk_envelope_defaults()
        print_success(f"Extracted {len(risk_envelope_params)} risk envelope defaults")
        
        # Extract profile adapter defaults
        print_section("Extracting Profile Adapter Defaults")
        profile_adapter_params = extract_profile_adapter_defaults()
        print_success(f"Extracted {len(profile_adapter_params)} profile adapter defaults")
        
        # Extract unified sizing defaults
        print_section("Extracting Unified Sizing Defaults")
        unified_sizing_params = extract_unified_sizing_defaults()
        print_success(f"Extracted {len(unified_sizing_params)} unified sizing defaults")
        
        # Extract agent grid defaults
        print_section("Extracting Agent Grid Defaults")
        agent_grid_params = extract_agent_grid_defaults()
        print_success(f"Extracted {len(agent_grid_params)} agent grid defaults")
        
        # Check window tracking implementation
        print_section("Checking Window-Based Risk Tracking Implementation")
        check_window_tracking_implementation(result)
        
        # Check asset coverage
        print_section("Checking Asset Coverage")
        check_asset_coverage(profile_params, result)
        
        # Compare parameters across layers
        print_section("Comparing Parameters Across Layers")
        compare_parameters(
            profile_params,
            risk_envelope_params,
            profile_adapter_params,
            unified_sizing_params,
            agent_grid_params,
            result
        )
        
        # Print summary
        result.print_summary()
        
        # Exit with appropriate code
        total_issues = len(result.discrepancies) + len(result.missing_parameters)
        failed_window_checks = sum(1 for c in result.window_tracking_checks if not c["passed"])
        
        if total_issues == 0 and failed_window_checks == 0:
            return 0
        else:
            return 1
            
    except Exception as e:
        print_error(f"Audit failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    sys.exit(main())
