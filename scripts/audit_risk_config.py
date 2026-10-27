#!/usr/bin/env python3
"""
Risk Configuration Audit Tool — Phase 1 of Production Audit

This script maps all configuration sources that can influence risk sizing,
position size, or trade enablement in the MERID trading system.

Usage:
    python scripts/audit_risk_config.py
    python scripts/audit_risk_config.py --output-json risk_config_audit.json
    python scripts/audit_risk_config.py --check-overrides

Exit codes:
    0: All checks passed, no unsafe overrides found
    1: Unsafe configuration overrides detected
    2: Error running audit
"""

import os
import sys
import json
import yaml
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any, Set
from collections import defaultdict
import argparse

# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"

# Files to audit
YAML_FILES = [
    "portfolio_optimizer.yaml",
    "kalshi_agent_grid.yaml", 
    "trade_hold_config.yaml",
    "settings.yaml",
    "kalshi_crypto_hedging.yaml",
    "rate_limits.yaml",
]

# Risk-related keywords to search for
RISK_KEYWORDS = [
    "risk", "risk_pct", "risk_per_trade", "risk_per_cycle", "max_risk", "min_risk",
    "position_size", "size_pct", "max_size", "min_size", "sizing",
    "bankroll", "equity", "leverage", "margin",
    "max_order", "max_contracts", "max_notional", "max_position",
    "top_n", "max_edges", "max_trades",
    "kelly", "fraction", "alloc",
]

# Dangerous override patterns
DANGEROUS_PATTERNS = [
    "emergency_override",
    "debug_mode", 
    "aggressive_mode",
    "high_risk_mode",
    "legacy_sizing",
    "bypass_guard",
    "unlimited",
    "override_cap",
]


@dataclass
class ConfigFileInfo:
    """Information about a configuration file."""
    path: str
    scope: str  # "global", "per-asset", "per-strategy", "per-agent", "per-env"
    environments: List[str]  # dev, sim, paper, live
    live_enabled: bool
    loader: str  # Which module loads this file
    risk_keys: Dict[str, Any]  # Risk-related keys and values
    raw_content: Optional[Dict] = None


@dataclass
class RiskOverride:
    """A detected risk configuration override."""
    source: str  # File path or env var
    override_type: str  # "env_var", "yaml_key", "hardcoded", "dynamic"
    key: str
    value: Any
    default_value: Optional[Any] = None
    safety_status: str = "unknown"  # "safe", "unsafe", "unknown"
    description: str = ""


class RiskConfigAuditor:
    """Audits all risk-related configuration in the MERID system."""
    
    def __init__(self):
        self.config_files: List[ConfigFileInfo] = []
        self.overrides: List[RiskOverride] = []
        self.merged_config: Dict[str, Any] = {}
        self.warnings: List[str] = []
        
    def run_full_audit(self) -> Dict[str, Any]:
        """Execute complete configuration audit."""
        print("=" * 80)
        print("RISK CONFIGURATION AUDIT — MERID Trading System")
        print("=" * 80)
        print()
        
        # Phase 1.1: Enumerate all YAML config files
        self._audit_yaml_files()
        
        # Phase 1.2: Check environment variables
        self._audit_environment_variables()
        
        # Phase 1.3: Build merged config view
        self._build_merged_config()
        
        # Phase 1.4: Detect overrides
        self._detect_overrides()
        
        # Phase 1.5: Safety analysis
        self._analyze_safety()
        
        return self._generate_report()
    
    def _audit_yaml_files(self):
        """Audit all YAML configuration files."""
        print("[Phase 1.1] Auditing YAML configuration files...")
        print()
        
        for yaml_file in YAML_FILES:
            file_path = CONFIG_DIR / yaml_file
            if not file_path.exists():
                self.warnings.append(f"Config file not found: {yaml_file}")
                continue
                
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = yaml.safe_load(f)
                    
                info = self._analyze_yaml_file(yaml_file, content)
                self.config_files.append(info)
                
                print(f"  ✓ {yaml_file}")
                print(f"    Scope: {info.scope}")
                print(f"    Environments: {', '.join(info.environments)}")
                print(f"    Live enabled: {info.live_enabled}")
                print(f"    Risk keys found: {len(info.risk_keys)}")
                
                if info.risk_keys:
                    for key, value in list(info.risk_keys.items())[:5]:
                        print(f"      - {key}: {value}")
                    if len(info.risk_keys) > 5:
                        print(f"      ... and {len(info.risk_keys) - 5} more")
                print()
                
            except Exception as e:
                self.warnings.append(f"Error parsing {yaml_file}: {e}")
                print(f"  ✗ {yaml_file} - ERROR: {e}")
                
    def _analyze_yaml_file(self, filename: str, content: Dict) -> ConfigFileInfo:
        """Analyze a single YAML configuration file."""
        # Determine scope based on filename and content
        scope = self._determine_scope(filename, content)
        environments = self._determine_environments(filename, content)
        live_enabled = self._is_live_enabled(filename, content)
        loader = self._determine_loader(filename)
        
        # Extract all risk-related keys
        risk_keys = self._extract_risk_keys(content)
        
        return ConfigFileInfo(
            path=str(CONFIG_DIR / filename),
            scope=scope,
            environments=environments,
            live_enabled=live_enabled,
            loader=loader,
            risk_keys=risk_keys,
            raw_content=content
        )
    
    def _determine_scope(self, filename: str, content: Dict) -> str:
        """Determine the scope of a config file."""
        if "agent" in filename.lower() or "grid" in filename.lower():
            return "per-agent"
        elif "portfolio" in filename.lower() or "optimizer" in filename.lower():
            return "global"
        elif "profile" in filename.lower():
            return "per-env"
        elif "hedging" in filename.lower():
            return "per-strategy"
        elif "trade_hold" in filename.lower():
            return "global"
        else:
            return "unknown"
    
    def _determine_environments(self, filename: str, content: Dict) -> List[str]:
        """Determine which environments this config applies to."""
        envs = []
        
        # Check for profiles section
        if isinstance(content, dict):
            if "profiles" in content:
                envs = list(content["profiles"].keys())
            elif "development" in content or "paper" in content or "live" in content:
                envs = ["development", "paper", "live"]
            else:
                envs = ["all"]
        else:
            envs = ["all"]
            
        return envs
    
    def _is_live_enabled(self, filename: str, content: Dict) -> bool:
        """Determine if this config is enabled in live mode."""
        if isinstance(content, dict):
            # Check profiles
            if "profiles" in content and "live" in content["profiles"]:
                profile = content["profiles"]["live"]
                if isinstance(profile, dict):
                    enabled = profile.get("enabled", True)
                    return enabled
            
            # Check top-level enabled flag
            enabled = content.get("enabled", True)
            return enabled
            
        return True
    
    def _determine_loader(self, filename: str) -> str:
        """Determine which module loads this config file."""
        loaders = {
            "portfolio_optimizer.yaml": "merid/portfolio/optimizer.py",
            "kalshi_agent_grid.yaml": "merid/trading/kalshi_trading_agent.py",
            "trade_hold_config.yaml": "merid/prediction/trade_hold_decision.py",
            "kalshi_crypto_hedging.yaml": "merid/hedging/config.py",
            "settings.yaml": "core/settings.py",
        }
        return loaders.get(filename, "unknown")
    
    def _extract_risk_keys(self, content: Dict, prefix: str = "") -> Dict[str, Any]:
        """Recursively extract all risk-related keys from config."""
        risk_keys = {}
        
        if not isinstance(content, dict):
            return risk_keys
            
        for key, value in content.items():
            full_key = f"{prefix}.{key}" if prefix else key
            
            # Check if key matches risk keywords
            is_risk_key = any(risk_word in key.lower() for risk_word in RISK_KEYWORDS)
            
            # Also check dangerous patterns
            is_dangerous = any(pattern in key.lower() for pattern in DANGEROUS_PATTERNS)
            
            if is_risk_key or is_dangerous:
                risk_keys[full_key] = {
                    "value": value,
                    "is_dangerous": is_dangerous,
                }
            
            # Recurse into nested dicts
            if isinstance(value, dict):
                nested = self._extract_risk_keys(value, full_key)
                risk_keys.update(nested)
                
        return risk_keys
    
    def _audit_environment_variables(self):
        """Audit environment variable overrides."""
        print("[Phase 1.2] Auditing environment variables...")
        print()
        
        # Critical env vars that can override risk settings
        critical_env_vars = [
            "USE_TOPN_ALLOCATOR",
            "MAX_CYCLE_RISK_PCT",
            "MAX_TOTAL_RISK_PCT",
            "MERID_MAX_RISK_PER_TRADE",
            "MERID_KELLY_FRACTION",
            "MERID_POSITION_MAX_PCT",
            "KALSHI_CT_PROFILE",
            "MERID_TRADING_MODE",
        ]
        
        for var in critical_env_vars:
            value = os.getenv(var)
            if value:
                print(f"  ✓ {var}={value}")
                
                # Determine if this is safe
                safety = self._assess_env_safety(var, value)
                
                self.overrides.append(RiskOverride(
                    source=f"Environment Variable",
                    override_type="env_var",
                    key=var,
                    value=value,
                    safety_status=safety,
                    description=f"Environment variable override for {var}"
                ))
            else:
                print(f"  ○ {var} (not set)")
                
        print()
    
    def _assess_env_safety(self, var: str, value: str) -> str:
        """Assess whether an environment variable setting is safe."""
        var_lower = var.lower()
        
        # Check for dangerous values
        if "risk" in var_lower or "pct" in var_lower:
            try:
                pct_value = float(value)
                if pct_value > 0.02:  # > 2%
                    return "unsafe"
                elif pct_value > 0.015:  # > 1.5%
                    return "caution"
                else:
                    return "safe"
            except:
                pass
        
        # Check for enable/disable flags
        if "topn" in var_lower or "allocator" in var_lower:
            if value.lower() in ("true", "1", "yes"):
                return "safe"
            else:
                return "unsafe"  # Disabling the safe allocator is unsafe
                
        return "unknown"
    
    def _build_merged_config(self):
        """Build a merged view of all configuration sources."""
        print("[Phase 1.3] Building merged configuration view...")
        print()
        
        # Start with defaults
        self.merged_config = {
            "max_cycle_risk_pct": 0.02,
            "max_total_risk_pct": 0.02,
            "max_risk_per_trade_pct": 0.015,
            "kelly_fraction": 0.20,
            "use_topn_allocator": False,
            "max_edges_per_cycle": 3,
            "min_contracts": 1,
            "max_concurrent_assets": 3,
        }
        
        # Apply YAML configs (in order of precedence)
        for config_file in self.config_files:
            if not config_file.live_enabled:
                continue
                
            for key, info in config_file.risk_keys.items():
                # Map YAML keys to canonical names
                canonical = self._canonicalize_key(key)
                if canonical:
                    self.merged_config[canonical] = info["value"]
                    
        # Apply environment variables (highest precedence)
        for override in self.overrides:
            if override.override_type == "env_var":
                canonical = self._canonicalize_key(override.key)
                if canonical:
                    try:
                        # Try to convert to number
                        value = float(override.value)
                        if value == int(value):
                            value = int(value)
                    except:
                        value = override.value
                        
                    self.merged_config[canonical] = value
                    
        print("  Merged risk configuration:")
        for key, value in sorted(self.merged_config.items()):
            print(f"    {key}: {value}")
        print()
    
    def _canonicalize_key(self, key: str) -> Optional[str]:
        """Map a config key to its canonical name."""
        key_lower = key.lower().replace(".", "_")
        
        mappings = {
            "max_cycle_risk_pct": ["max_cycle_risk", "cycle_risk_pct", "max_cycle_risk_pct"],
            "max_total_risk_pct": ["max_total_risk", "total_risk_pct", "max_total_risk_pct"],
            "max_risk_per_trade_pct": ["max_risk_per_trade", "risk_per_trade", "max_risk_pct_per_trade"],
            "use_topn_allocator": ["use_topn_allocator", "topn_allocator", "use_top_n"],
            "max_edges_per_cycle": ["max_edges", "max_edges_per_cycle", "top_n"],
        }
        
        for canonical, variants in mappings.items():
            if any(var in key_lower for var in variants):
                return canonical
                
        return None
    
    def _detect_overrides(self):
        """Detect configuration overrides that might bypass the 1-2% rule."""
        print("[Phase 1.4] Detecting overrides...")
        print()
        
        # Check for dangerous patterns in YAML files
        for config_file in self.config_files:
            for key, info in config_file.risk_keys.items():
                if info.get("is_dangerous"):
                    self.overrides.append(RiskOverride(
                        source=config_file.path,
                        override_type="yaml_key",
                        key=key,
                        value=info["value"],
                        safety_status="unsafe",
                        description=f"Dangerous key pattern detected in {config_file.path}"
                    ))
                    print(f"  ⚠️  DANGEROUS: {key} in {config_file.path}")
                    
        print(f"  Found {len(self.overrides)} potential overrides")
        print()
    
    def _analyze_safety(self):
        """Analyze overall safety of configuration."""
        print("[Phase 1.5] Analyzing safety...")
        print()
        
        # Check key safety criteria
        unsafe_count = sum(1 for o in self.overrides if o.safety_status == "unsafe")
        caution_count = sum(1 for o in self.overrides if o.safety_status == "caution")
        
        # Check if TopN allocator is enabled
        use_topn = self.merged_config.get("use_topn_allocator", False)
        
        # Check cycle risk cap
        max_cycle = self.merged_config.get("max_cycle_risk_pct", 0.02)
        
        print("  Safety Analysis:")
        print(f"    - TopN Allocator enabled: {use_topn} {'✓' if use_topn else '✗'}")
        print(f"    - Max cycle risk: {max_cycle}% {'✓' if max_cycle <= 0.02 else '✗'}")
        print(f"    - Unsafe overrides: {unsafe_count}")
        print(f"    - Caution overrides: {caution_count}")
        print()
        
        if not use_topn:
            self.warnings.append("CRITICAL: TopN Allocator is DISABLED — using legacy Kelly sizing")
            
        if max_cycle > 0.02:
            self.warnings.append(f"CRITICAL: Max cycle risk is {max_cycle}% > 2%")
            
        if unsafe_count > 0:
            self.warnings.append(f"WARNING: {unsafe_count} unsafe configuration overrides detected")
    
    def _generate_report(self) -> Dict[str, Any]:
        """Generate final audit report."""
        report = {
            "audit_timestamp": str(pd.Timestamp.now()) if 'pd' in dir() else "N/A",
            "config_files": [asdict(f) for f in self.config_files],
            "merged_config": self.merged_config,
            "overrides": [
                {
                    "source": o.source,
                    "type": o.override_type,
                    "key": o.key,
                    "value": str(o.value),
                    "safety_status": o.safety_status,
                    "description": o.description,
                }
                for o in self.overrides
            ],
            "warnings": self.warnings,
            "is_safe": len([w for w in self.warnings if w.startswith("CRITICAL")]) == 0,
        }
        
        return report
    
    def print_summary(self):
        """Print human-readable summary."""
        print("=" * 80)
        print("AUDIT SUMMARY")
        print("=" * 80)
        print()
        
        print(f"Configuration files audited: {len(self.config_files)}")
        print(f"Environment variables checked: {len([o for o in self.overrides if o.override_type == 'env_var'])}")
        print(f"Potential overrides detected: {len(self.overrides)}")
        print(f"Warnings: {len(self.warnings)}")
        print()
        
        if self.warnings:
            print("WARNINGS:")
            for warning in self.warnings:
                prefix = "🚨" if warning.startswith("CRITICAL") else "⚠️"
                print(f"  {prefix} {warning}")
            print()
            
        # Final verdict
        critical_warnings = [w for w in self.warnings if w.startswith("CRITICAL")]
        if critical_warnings:
            print("❌ AUDIT FAILED — Critical issues must be resolved before trading")
            return 1
        elif self.warnings:
            print("⚠️  AUDIT PASSED WITH WARNINGS — Review warnings before trading")
            return 0
        else:
            print("✅ AUDIT PASSED — Configuration is safe for trading")
            return 0


def main():
    parser = argparse.ArgumentParser(description="Risk Configuration Audit Tool")
    parser.add_argument("--output-json", help="Save report to JSON file")
    parser.add_argument("--check-overrides", action="store_true", help="Only check for overrides")
    args = parser.parse_args()
    
    auditor = RiskConfigAuditor()
    report = auditor.run_full_audit()
    
    if args.output_json:
        with open(args.output_json, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        print(f"Report saved to {args.output_json}")
        
    exit_code = auditor.print_summary()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
