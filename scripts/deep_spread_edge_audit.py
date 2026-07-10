#!/usr/bin/env python3
"""
Deep Spread/Edge Audit Script for MERID 15M Kalshi Crypto Trading System

This script performs a comprehensive audit across the entire trading pipeline to uncover:
1. Spread configuration misalignments (upstream, downstream, midstream)
2. Edge calculation inconsistencies
3. Silent blockers in candidate generation
4. Execution latency issues that may cause missed trades
5. Any discrepancies between spread and edge thresholds

Run this script to identify why the system hasn't executed a trade in almost an hour.
"""

import os
import sys
import re
import yaml
import asyncio
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass, field
from decimal import Decimal
import json

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class SpreadConfig:
    """Spread configuration from a source."""
    source: str
    location: str
    max_spread_cents: Optional[float] = None
    min_spread_cents: Optional[float] = None
    spread_gate_cents: Optional[float] = None
    max_spread_for_edge: Optional[Dict[str, float]] = None
    line_number: Optional[int] = None


@dataclass
class EdgeConfig:
    """Edge configuration from a source."""
    source: str
    location: str
    min_edge_pct: Optional[float] = None
    max_edge_pct: Optional[float] = None
    edge_threshold: Optional[float] = None
    line_number: Optional[int] = None


@dataclass
class LatencyConfig:
    """Latency/timing configuration."""
    source: str
    location: str
    latency_ms: Optional[float] = None
    timeout_ms: Optional[float] = None
    description: str = ""
    line_number: Optional[int] = None


@dataclass
class AuditIssue:
    """An audit issue found."""
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    category: str  # SPREAD, EDGE, LATENCY, BLOCKER, MISALIGNMENT
    description: str
    location: str
    expected: str
    actual: str
    recommendation: str


class DeepSpreadEdgeAuditor:
    """Comprehensive auditor for spread/edge configuration and execution pipeline."""
    
    def __init__(self):
        self.issues: List[AuditIssue] = []
        self.spread_configs: List[SpreadConfig] = []
        self.edge_configs: List[EdgeConfig] = []
        self.latency_configs: List[LatencyConfig] = []
        self.profile_config: Dict[str, Any] = {}
        
    def add_issue(self, severity: str, category: str, description: str, 
                  location: str, expected: str, actual: str, recommendation: str):
        """Add an audit issue."""
        self.issues.append(AuditIssue(
            severity=severity,
            category=category,
            description=description,
            location=location,
            expected=expected,
            actual=actual,
            recommendation=recommendation
        ))
    
    def load_profile_config(self) -> bool:
        """Load the production profile YAML."""
        profile_path = PROJECT_ROOT / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        if not profile_path.exists():
            self.add_issue(
                severity="CRITICAL",
                category="BLOCKER",
                description="Production profile YAML not found",
                location=str(profile_path),
                expected="kalshi_crypto_15m_v2.yaml exists",
                actual="File not found",
                recommendation="Ensure profile YAML exists at config/profiles/kalshi_crypto_15m_v2.yaml"
            )
            return False
        
        try:
            with open(profile_path, 'r', encoding='utf-8') as f:
                self.profile_config = yaml.safe_load(f)
            print(f"[OK] Loaded profile config from {profile_path}")
            return True
        except Exception as e:
            self.add_issue(
                severity="CRITICAL",
                category="BLOCKER",
                description=f"Failed to load profile YAML: {e}",
                location=str(profile_path),
                expected="Valid YAML",
                actual=f"Error: {e}",
                recommendation="Fix YAML syntax or permissions"
            )
            return False
    
    def audit_profile_spread_config(self):
        """Audit spread configuration in profile YAML."""
        if not self.profile_config:
            return
        
        # Check universe.max_spread_cents
        universe = self.profile_config.get('universe', {})
        universe_max_spread = universe.get('max_spread_cents')
        
        if universe_max_spread is not None:
            self.spread_configs.append(SpreadConfig(
                source="profile_yaml",
                location="universe.max_spread_cents",
                max_spread_cents=universe_max_spread
            ))
            print(f"  universe.max_spread_cents: {universe_max_spread}c")
        
        # Check guardrails.min_spread_gate_cents
        guardrails = self.profile_config.get('guardrails', {})
        min_spread_gate = guardrails.get('min_spread_gate_cents')
        
        if min_spread_gate is not None:
            self.spread_configs.append(SpreadConfig(
                source="profile_yaml",
                location="guardrails.min_spread_gate_cents",
                min_spread_cents=min_spread_gate
            ))
            print(f"  guardrails.min_spread_gate_cents: {min_spread_gate}c")
        
        # Check guardrails.max_spread_for_edge
        max_spread_for_edge = guardrails.get('max_spread_for_edge')
        
        if max_spread_for_edge:
            self.spread_configs.append(SpreadConfig(
                source="profile_yaml",
                location="guardrails.max_spread_for_edge",
                max_spread_for_edge=max_spread_for_edge
            ))
            print(f"  guardrails.max_spread_for_edge: {max_spread_for_edge}")
        
        # Check momentum_fvg.spread_gate_cents
        momentum_fvg = self.profile_config.get('momentum_fvg', {})
        spread_gate = momentum_fvg.get('spread_gate_cents')
        
        if spread_gate is not None:
            self.spread_configs.append(SpreadConfig(
                source="profile_yaml",
                location="momentum_fvg.spread_gate_cents",
                spread_gate_cents=spread_gate
            ))
            print(f"  momentum_fvg.spread_gate_cents: {spread_gate}c")
    
    def audit_unified_edge_fallback(self):
        """Audit unified_edge.py for hardcoded fallback values."""
        unified_edge_path = PROJECT_ROOT / "merid" / "prediction" / "unified_edge.py"
        
        if not unified_edge_path.exists():
            self.add_issue(
                severity="HIGH",
                category="BLOCKER",
                description="unified_edge.py not found",
                location=str(unified_edge_path),
                expected="unified_edge.py exists",
                actual="File not found",
                recommendation="Ensure unified_edge.py exists at merid/prediction/unified_edge.py"
            )
            return
        
        with open(unified_edge_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Look for max_spread_for_edge fallback
        fallback_pattern = r'max_spread_for_edge\s*=\s*(\d+)'
        matches = re.finditer(fallback_pattern, content)
        
        for match in matches:
            line_num = content[:match.start()].count('\n') + 1
            fallback_value = int(match.group(1))
            
            self.spread_configs.append(SpreadConfig(
                source="unified_edge.py",
                location=f"line {line_num}",
                max_spread_cents=float(fallback_value),
                line_number=line_num
            ))
            
            print(f"  unified_edge.py line {line_num}: max_spread_for_edge fallback = {fallback_value}c")
            
            # Check if this matches profile
            profile_default = self.profile_config.get('guardrails', {}).get('max_spread_for_edge', {}).get('default')
            
            if profile_default and fallback_value != profile_default:
                self.add_issue(
                    severity="CRITICAL",
                    category="MISALIGNMENT",
                    description=f"unified_edge.py fallback ({fallback_value}c) does not match profile default ({profile_default}c)",
                    location=f"unified_edge.py line {line_num}",
                    expected=f"Fallback should match profile default: {profile_default}c",
                    actual=f"Fallback is {fallback_value}c",
                    recommendation=f"Update unified_edge.py fallback to {profile_default}c or remove hardcoded value"
                )
    
    def audit_candidate_optimizer_spread(self):
        """Audit candidate_optimizer.py for spread thresholds."""
        optimizer_path = PROJECT_ROOT / "merid" / "prediction" / "candidate_optimizer.py"
        
        if not optimizer_path.exists():
            return
        
        with open(optimizer_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Look for MAX_SPREAD_CENTS constant
        max_spread_pattern = r'MAX_SPREAD_CENTS\s*=\s*(\d+)'
        matches = re.finditer(max_spread_pattern, content)
        
        for match in matches:
            line_num = content[:match.start()].count('\n') + 1
            value = int(match.group(1))
            
            self.spread_configs.append(SpreadConfig(
                source="candidate_optimizer.py",
                location=f"line {line_num}",
                max_spread_cents=float(value),
                line_number=line_num
            ))
            
            print(f"  candidate_optimizer.py line {line_num}: MAX_SPREAD_CENTS = {value}c")
            
            # Check if this matches profile
            profile_max = self.profile_config.get('universe', {}).get('max_spread_cents')
            
            if profile_max and value != profile_max:
                self.add_issue(
                    severity="HIGH",
                    category="MISALIGNMENT",
                    description=f"candidate_optimizer.py MAX_SPREAD_CENTS ({value}c) does not match profile universe.max_spread_cents ({profile_max}c)",
                    location=f"candidate_optimizer.py line {line_num}",
                    expected=f"Should match profile: {profile_max}c",
                    actual=f"Hardcoded as {value}c",
                    recommendation=f"Update MAX_SPREAD_CENTS to {profile_max}c or load from profile"
                )
    
    def audit_agent_grid_hardcoded_spread(self):
        """Audit agent_grid_15m.py for hardcoded spread thresholds."""
        agent_grid_path = PROJECT_ROOT / "merid" / "loop_15m.py"  # Main loop file
        
        if not agent_grid_path.exists():
            agent_grid_path = PROJECT_ROOT / "merid" / "prediction" / "agent_grid_15m.py"
        
        if not agent_grid_path.exists():
            return
        
        with open(agent_grid_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Look for hardcoded spread comparisons
        hardcoded_patterns = [
            r'spread\s*[>]=\s*(\d+)',  # spread >= X
            r'spread\s*[<]=\s*(\d+)',   # spread <= X
            r'max_spread\s*=\s*(\d+)',  # max_spread = X
        ]
        
        for pattern in hardcoded_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                line_num = content[:match.start()].count('\n') + 1
                value = int(match.group(1))
                
                # Only flag if it looks like a spread threshold (reasonable range 1-100)
                if 1 <= value <= 100:
                    print(f"  {agent_grid_path.name} line {line_num}: hardcoded spread threshold = {value}c")
                    
                    profile_max = self.profile_config.get('universe', {}).get('max_spread_cents')
                    
                    if profile_max and value != profile_max:
                        self.add_issue(
                            severity="MEDIUM",
                            category="MISALIGNMENT",
                            description=f"Hardcoded spread threshold ({value}c) in {agent_grid_path.name}",
                            location=f"{agent_grid_path.name} line {line_num}",
                            expected=f"Should use profile value: {profile_max}c",
                            actual=f"Hardcoded as {value}c",
                            recommendation="Replace hardcoded value with profile-driven configuration"
                        )
    
    def audit_edge_thresholds(self):
        """Audit edge threshold configurations."""
        # Check profile for edge thresholds
        strategies = self.profile_config.get('strategies', {})
        
        for strategy_name, strategy_config in strategies.items():
            min_edge = strategy_config.get('min_edge')
            if min_edge is not None:
                self.edge_configs.append(EdgeConfig(
                    source="profile_yaml",
                    location=f"strategies.{strategy_name}.min_edge",
                    min_edge_pct=min_edge
                ))
                print(f"  strategies.{strategy_name}.min_edge: {min_edge}")
        
        # Check unified_edge.py for edge thresholds
        unified_edge_path = PROJECT_ROOT / "merid" / "prediction" / "unified_edge.py"
        if unified_edge_path.exists():
            with open(unified_edge_path, 'r') as f:
                content = f.read()
            
            # Look for min_edge thresholds
            min_edge_pattern = r'min_edge\s*[<>=]+\s*([\d.]+)'
            matches = re.finditer(min_edge_pattern, content)
            
            for match in matches:
                line_num = content[:match.start()].count('\n') + 1
                value = float(match.group(1))
                
                self.edge_configs.append(EdgeConfig(
                    source="unified_edge.py",
                    location=f"line {line_num}",
                    min_edge_pct=value,
                    line_number=line_num
                ))
                print(f"  unified_edge.py line {line_num}: min_edge threshold = {value}")
    
    def audit_execution_latency(self):
        """Audit execution latency configuration."""
        # Check profile for throttling/cooldown settings
        throttling = self.profile_config.get('throttling', {})
        
        per_asset_cooldown = throttling.get('per_asset_cooldown_sec')
        if per_asset_cooldown:
            self.latency_configs.append(LatencyConfig(
                source="profile_yaml",
                location="throttling.per_asset_cooldown_sec",
                latency_ms=per_asset_cooldown * 1000,
                description="Per-asset cooldown between orders"
            ))
            print(f"  throttling.per_asset_cooldown_sec: {per_asset_cooldown}s ({per_asset_cooldown * 1000}ms)")
        
        global_window = throttling.get('global_orders_window_sec')
        if global_window:
            print(f"  throttling.global_orders_window_sec: {global_window}s")
        
        # Check order router for latency tracking
        order_router_path = PROJECT_ROOT / "merid" / "event_venues" / "kalshi" / "order_router.py"
        if order_router_path.exists():
            with open(order_router_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Look for latency thresholds
            latency_pattern = r'latency.*[<>=]+\s*(\d+)'
            matches = re.finditer(latency_pattern, content, re.IGNORECASE)
            
            for match in matches:
                line_num = content[:match.start()].count('\n') + 1
                value = int(match.group(1))
                
                self.latency_configs.append(LatencyConfig(
                    source="order_router.py",
                    location=f"line {line_num}",
                    latency_ms=float(value),
                    line_number=line_num
                ))
                print(f"  order_router.py line {line_num}: latency threshold = {value}ms")
    
    def check_spread_edge_compatibility(self):
        """Check if spread and edge thresholds are compatible."""
        # Get key spread values
        universe_max_spread = self.profile_config.get('universe', {}).get('max_spread_cents')
        guardrails_max_spread_edge = self.profile_config.get('guardrails', {}).get('max_spread_for_edge', {}).get('default')
        min_spread_gate = self.profile_config.get('guardrails', {}).get('min_spread_gate_cents')
        
        # Get key edge values
        strategies = self.profile_config.get('strategies', {})
        min_edges = [s.get('min_edge') for s in strategies.values() if s.get('min_edge')]
        avg_min_edge = sum(min_edges) / len(min_edges) if min_edges else None
        
        print("\n=== SPREAD/EDGE COMPATIBILITY CHECK ===")
        
        # Check 1: universe.max_spread_cents should be >= guardrails.max_spread_for_edge.default
        if universe_max_spread and guardrails_max_spread_edge:
            if universe_max_spread < guardrails_max_spread_edge:
                self.add_issue(
                    severity="CRITICAL",
                    category="MISALIGNMENT",
                    description=f"universe.max_spread_cents ({universe_max_spread}c) < guardrails.max_spread_for_edge.default ({guardrails_max_spread_edge}c)",
                    location="profile_yaml",
                    expected=f"universe.max_spread_cents >= guardrails.max_spread_for_edge.default",
                    actual=f"{universe_max_spread}c < {guardrails_max_spread_edge}c",
                    recommendation=f"Increase universe.max_spread_cents to at least {guardrails_max_spread_edge}c"
                )
            else:
                print(f"[OK] universe.max_spread_cents ({universe_max_spread}c) >= guardrails.max_spread_for_edge.default ({guardrails_max_spread_edge}c)")
        
        # Check 2: min_spread_gate_cents should be <= universe.max_spread_cents
        if min_spread_gate and universe_max_spread:
            if min_spread_gate > universe_max_spread:
                self.add_issue(
                    severity="HIGH",
                    category="MISALIGNMENT",
                    description=f"min_spread_gate_cents ({min_spread_gate}c) > universe.max_spread_cents ({universe_max_spread}c)",
                    location="profile_yaml",
                    expected=f"min_spread_gate_cents <= universe.max_spread_cents",
                    actual=f"{min_spread_gate}c > {universe_max_spread}c",
                    recommendation=f"Decrease min_spread_gate_cents to <= {universe_max_spread}c"
                )
            else:
                print(f"[OK] min_spread_gate_cents ({min_spread_gate}c) <= universe.max_spread_cents ({universe_max_spread}c)")
        
        # Check 3: Edge should be meaningfully larger than spread
        if avg_min_edge and universe_max_spread:
            # Convert edge % to cents (assuming 50c midpoint = 0.50 probability)
            # Edge of 2% at 50c = 1c edge
            edge_in_cents = avg_min_edge * 0.5  # Approximate conversion
            
            if edge_in_cents < universe_max_spread:
                self.add_issue(
                    severity="HIGH",
                    category="MISALIGNMENT",
                    description=f"Average min_edge ({avg_min_edge}% ≈ {edge_in_cents}c) < universe.max_spread_cents ({universe_max_spread}c)",
                    location="profile_yaml",
                    expected=f"min_edge should be >= 2x max_spread for profitable trading",
                    actual=f"Edge ({edge_in_cents}c) < spread ({universe_max_spread}c)",
                    recommendation=f"Increase min_edge or decrease max_spread_cents. Edge should be at least 2x spread for profitability."
                )
            else:
                print(f"[OK] Average min_edge ({avg_min_edge}% ≈ {edge_in_cents}c) >= universe.max_spread_cents ({universe_max_spread}c)")
    
    def check_silent_blockers(self):
        """Check for silent blockers that may prevent candidate generation."""
        print("\n=== SILENT BLOCKER CHECK ===")
        
        # Check 1: Signal mode
        signal_mode = self.profile_config.get('signal_mode')
        print(f"  signal_mode: {signal_mode}")
        
        if signal_mode == "disabled":
            self.add_issue(
                severity="CRITICAL",
                category="BLOCKER",
                description="signal_mode is disabled - no signals will be generated",
                location="profile_yaml.signal_mode",
                expected="signal_mode should be enabled (momentum_fvg, mean_reversion, hybrid, price_based)",
                actual="signal_mode = disabled",
                recommendation="Enable signal_mode to a valid strategy"
            )
        
        # Check 2: Dry run mode
        dry_run = self.profile_config.get('dry_run')
        print(f"  dry_run: {dry_run}")
        
        if dry_run:
            self.add_issue(
                severity="HIGH",
                category="BLOCKER",
                description="dry_run is enabled - orders will not be submitted",
                location="profile_yaml.dry_run",
                expected="dry_run should be false for live trading",
                actual="dry_run = true",
                recommendation="Set dry_run to false for live trading"
            )
        
        # Check 3: Catalog staleness enforcement
        catalog_staleness_enforced = self.profile_config.get('catalog_staleness_enforced')
        print(f"  catalog_staleness_enforced: {catalog_staleness_enforced}")
        
        # Check 4: Operation mode
        operation_mode = self.profile_config.get('operation_mode')
        print(f"  operation_mode: {operation_mode}")
        
        # Check 5: Correlation tracking (may block multi-asset trading)
        correlation_tracking = self.profile_config.get('correlation_tracking', {})
        correlation_enabled = correlation_tracking.get('enabled')
        print(f"  correlation_tracking.enabled: {correlation_enabled}")
        
        if correlation_enabled:
            self.add_issue(
                severity="MEDIUM",
                category="BLOCKER",
                description="correlation_tracking is enabled - may block multi-asset trading in 15m window",
                location="profile_yaml.correlation_tracking.enabled",
                expected="correlation_tracking should be disabled for 15m crypto prediction markets",
                actual="correlation_tracking = true",
                recommendation="Set correlation_tracking.enabled to false (as documented in profile)"
            )
        
        # Check 6: Dynamic sizing (may interfere with risk limits)
        dynamic_sizing = self.profile_config.get('dynamic_sizing', {})
        dynamic_sizing_enabled = dynamic_sizing.get('enabled')
        print(f"  dynamic_sizing.enabled: {dynamic_sizing_enabled}")
        
        # Check 7: Order scaling (conflicts with 1-contract model)
        order_scaling = self.profile_config.get('order_scaling', {})
        order_scaling_enabled = order_scaling.get('enabled')
        print(f"  order_scaling.enabled: {order_scaling_enabled}")
        
        if order_scaling_enabled:
            self.add_issue(
                severity="MEDIUM",
                category="BLOCKER",
                description="order_scaling is enabled - conflicts with 1-contract-per-order slot-based model",
                location="profile_yaml.order_scaling.enabled",
                expected="order_scaling should be disabled for slot-based model",
                actual="order_scaling = true",
                recommendation="Set order_scaling.enabled to false"
            )
    
    def generate_report(self):
        """Generate audit report."""
        print("\n" + "="*80)
        print("AUDIT REPORT")
        print("="*80)
        
        # Summary
        critical = sum(1 for i in self.issues if i.severity == "CRITICAL")
        high = sum(1 for i in self.issues if i.severity == "HIGH")
        medium = sum(1 for i in self.issues if i.severity == "MEDIUM")
        low = sum(1 for i in self.issues if i.severity == "LOW")
        
        print(f"\nSUMMARY:")
        print(f"  CRITICAL: {critical}")
        print(f"  HIGH: {high}")
        print(f"  MEDIUM: {medium}")
        print(f"  LOW: {low}")
        print(f"  TOTAL: {len(self.issues)}")
        
        # Group by category
        print(f"\nISSUES BY CATEGORY:")
        categories = {}
        for issue in self.issues:
            if issue.category not in categories:
                categories[issue.category] = []
            categories[issue.category].append(issue)
        
        for category, issues in sorted(categories.items()):
            print(f"  {category}: {len(issues)}")
        
        # Detailed issues
        if self.issues:
            print(f"\nDETAILED ISSUES:")
            print("-" * 80)
            
            # Sort by severity
            severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
            sorted_issues = sorted(self.issues, key=lambda x: severity_order.get(x.severity, 99))
            
            for i, issue in enumerate(sorted_issues, 1):
                print(f"\n{i}. [{issue.severity}] {issue.category}")
                print(f"   Description: {issue.description}")
                print(f"   Location: {issue.location}")
                print(f"   Expected: {issue.expected}")
                print(f"   Actual: {issue.actual}")
                print(f"   Recommendation: {issue.recommendation}")
        else:
            print(f"\n[OK] No issues found - system is well aligned!")
        
        # Configuration summary
        print(f"\n" + "="*80)
        print("CONFIGURATION SUMMARY")
        print("="*80)
        
        print(f"\nSpread Configurations Found:")
        for config in self.spread_configs:
            details = []
            if config.max_spread_cents is not None:
                details.append(f"max_spread={config.max_spread_cents}c")
            if config.min_spread_cents is not None:
                details.append(f"min_spread={config.min_spread_cents}c")
            if config.spread_gate_cents is not None:
                details.append(f"spread_gate={config.spread_gate_cents}c")
            if config.max_spread_for_edge is not None:
                details.append(f"max_spread_for_edge={config.max_spread_for_edge}")
            
            line_info = f" (line {config.line_number})" if config.line_number else ""
            print(f"  {config.source}.{config.location}{line_info}: {', '.join(details)}")
        
        print(f"\nEdge Configurations Found:")
        for config in self.edge_configs:
            details = []
            if config.min_edge_pct is not None:
                details.append(f"min_edge={config.min_edge_pct}%")
            if config.max_edge_pct is not None:
                details.append(f"max_edge={config.max_edge_pct}%")
            
            line_info = f" (line {config.line_number})" if config.line_number else ""
            print(f"  {config.source}.{config.location}{line_info}: {', '.join(details)}")
        
        print(f"\nLatency Configurations Found:")
        for config in self.latency_configs:
            details = []
            if config.latency_ms is not None:
                details.append(f"latency={config.latency_ms}ms")
            if config.timeout_ms is not None:
                details.append(f"timeout={config.timeout_ms}ms")
            if config.description:
                details.append(config.description)
            
            line_info = f" (line {config.line_number})" if config.line_number else ""
            print(f"  {config.source}.{config.location}{line_info}: {', '.join(details)}")
        
        print(f"\n" + "="*80)
        
        # Return exit code based on critical issues
        return 1 if critical > 0 else 0
    
    def run(self):
        """Run the full audit."""
        print("="*80)
        print("DEEP SPREAD/EDGE AUDIT FOR MERID 15M KALSHI CRYPTO TRADING SYSTEM")
        print("="*80)
        
        # Load profile
        if not self.load_profile_config():
            return self.generate_report()
        
        # Audit spread configurations
        print("\n=== AUDITING SPREAD CONFIGURATIONS ===")
        self.audit_profile_spread_config()
        self.audit_unified_edge_fallback()
        self.audit_candidate_optimizer_spread()
        self.audit_agent_grid_hardcoded_spread()
        
        # Audit edge configurations
        print("\n=== AUDITING EDGE CONFIGURATIONS ===")
        self.audit_edge_thresholds()
        
        # Audit execution latency
        print("\n=== AUDITING EXECUTION LATENCY ===")
        self.audit_execution_latency()
        
        # Check compatibility
        self.check_spread_edge_compatibility()
        
        # Check silent blockers
        self.check_silent_blockers()
        
        # Generate report
        return self.generate_report()


def main():
    """Main entry point."""
    auditor = DeepSpreadEdgeAuditor()
    exit_code = auditor.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
