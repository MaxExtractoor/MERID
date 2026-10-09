"""
Comprehensive script to expose flaws in trading risk and execution guards,
and gaps between execution and exit systems.

This script systematically checks for:
1. Multiple competing risk guard systems (contamination risk)
2. Window-based risk limit implementation gaps
3. Exit system communication gaps with risk guards
4. Recording mechanism inconsistencies
5. Legacy vs production code contamination
6. End-to-end execution-to-exit flow gaps

Run this script to identify potential vulnerabilities before production deployment.
"""

import sys
import os
import importlib
import inspect
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass
from enum import Enum


class Severity(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


@dataclass
class Flaw:
    """Represents a discovered flaw in the trading system."""
    category: str
    severity: Severity
    title: str
    description: str
    location: str
    evidence: str
    recommendation: str


class FlawExposure:
    """Main class to expose trading risk and execution flaws."""
    
    def __init__(self):
        self.flaws: List[Flaw] = []
        self.workspace_root = Path("c:/Dev/MERID")
        
    def add_flaw(self, category: str, severity: Severity, title: str, 
                 description: str, location: str, evidence: str, recommendation: str):
        """Add a discovered flaw to the list."""
        self.flaws.append(Flaw(
            category=category,
            severity=severity,
            title=title,
            description=description,
            location=location,
            evidence=evidence,
            recommendation=recommendation
        ))
    
    def check_multiple_risk_guards(self):
        """Check for multiple competing risk guard systems."""
        print("\n" + "="*80)
        print("CHECKING FOR MULTIPLE RISK GUARD SYSTEMS")
        print("="*80)
        
        risk_guards = {
            "merid.risk.risk_guard": "Legacy RiskGuard with kill switch, daily loss limits",
            "merid.guards.global_risk_guard": "DEPRECATED GlobalRiskGuard with cycle risk caps",
            "merid.guards.global_execution_guard": "DEPRECATED GlobalExecutionGuard with bankroll cap",
            "merid.risk.unified_risk_manager": "Supposed single source of truth (UnifiedRiskManager)"
        }
        
        for module_name, description in risk_guards.items():
            try:
                module = importlib.import_module(module_name)
                print(f"✓ Found: {module_name}")
                print(f"  Description: {description}")
                
                # Check if module is marked as deprecated
                if hasattr(module, '__doc__') and module.__doc__:
                    if 'DEPRECATED' in module.__doc__ or 'deprecated' in module.__doc__.lower():
                        self.add_flaw(
                            category="RISK_GUARD_CONTAMINATION",
                            severity=Severity.HIGH,
                            title=f"Deprecated risk guard still importable: {module_name}",
                            description=f"Module {module_name} is marked as deprecated but can still be imported. "
                                      "This creates risk of legacy code paths being used in production.",
                            location=module_name,
                            evidence=f"Module docstring contains 'DEPRECATED': {module.__doc__[:200]}",
                            recommendation="Remove deprecated modules or ensure they cannot be imported. "
                                          "Add import-time errors to prevent accidental usage."
                        )
                        print(f"  ⚠ WARNING: Module is marked as DEPRECATED")
                
                # Check for singleton instances
                for name, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and hasattr(obj, '_instance'):
                        print(f"  - Singleton class: {name}")
                        
            except ImportError as e:
                print(f"✗ Not found: {module_name} ({e})")
        
        # Check if deprecated guards are actually used by production code
        print("\nChecking for usage of deprecated guards in production code...")
        production_files = [
            "web/main_15m_lean.py",
            "merid/loop_15m.py",
            "merid/event_venues/kalshi/order_router.py",
            "merid/event_venues/kalshi/trading.py"
        ]
        
        for file_path in production_files:
            full_path = self.workspace_root / file_path
            if full_path.exists():
                content = full_path.read_text(encoding='utf-8', errors='ignore')
                
                if "global_risk_guard" in content or "GlobalRiskGuard" in content:
                    self.add_flaw(
                        category="RISK_GUARD_CONTAMINATION",
                        severity=Severity.CRITICAL,
                        title=f"Production code imports deprecated GlobalRiskGuard",
                        description=f"File {file_path} imports deprecated GlobalRiskGuard. "
                                  "This creates risk of inconsistent risk enforcement.",
                        location=file_path,
                        evidence="File contains 'global_risk_guard' or 'GlobalRiskGuard'",
                        recommendation="Replace with UnifiedRiskManager. Ensure all risk checks go through single source of truth."
                    )
                    print(f"  ⚠ CRITICAL: {file_path} uses deprecated GlobalRiskGuard")
                
                if "global_execution_guard" in content or "GlobalExecutionGuard" in content:
                    self.add_flaw(
                        category="RISK_GUARD_CONTAMINATION",
                        severity=Severity.CRITICAL,
                        title=f"Production code imports deprecated GlobalExecutionGuard",
                        description=f"File {file_path} imports deprecated GlobalExecutionGuard. "
                                  "This creates risk of inconsistent execution enforcement.",
                        location=file_path,
                        evidence="File contains 'global_execution_guard' or 'GlobalExecutionGuard'",
                        recommendation="Replace with UnifiedRiskManager. Ensure all execution checks go through single source of truth."
                    )
                    print(f"  ⚠ CRITICAL: {file_path} uses deprecated GlobalExecutionGuard")
    
    def check_window_limit_implementation(self):
        """Check window-based risk limit implementation consistency."""
        print("\n" + "="*80)
        print("CHECKING WINDOW-BASED RISK LIMIT IMPLEMENTATION")
        print("="*80)
        
        # Expected window limits from memory
        expected_limits = {
            "per_agent_window_risk_pct": 0.03,  # 3% per agent per 15-minute window
            "total_venue_window_risk_pct": 0.05,  # 5% total venue per 15-minute window
            "window_duration_seconds": 900  # 15 minutes
        }
        
        # Check order_gate.py for window limit implementation
        try:
            from merid.event_venues.kalshi.order_gate import PreTradeGate, GateMetrics
            print("✓ Found PreTradeGate in order_gate.py")
            
            # Check if window limit tracking exists
            if hasattr(GateMetrics, 'blocked_window_limit'):
                print("✓ PreTradeGate has window limit blocking metric")
            else:
                self.add_flaw(
                    category="WINDOW_LIMIT_IMPLEMENTATION",
                    severity=Severity.CRITICAL,
                    title="PreTradeGate missing window limit blocking metric",
                    description="PreTradeGate.GateMetrics does not have blocked_window_limit field. "
                              "Window limits may not be enforced.",
                    location="merid/event_venues/kalshi/order_gate.py",
                    evidence="GateMetrics class missing blocked_window_limit attribute",
                    recommendation="Add window limit tracking to GateMetrics and implement enforcement in PreTradeGate.check()"
                )
                print("✗ CRITICAL: PreTradeGate missing window limit blocking metric")
            
            # Check for window tracking state
            gate_source = inspect.getsource(PreTradeGate)
            if "window" in gate_source.lower() and "900" in gate_source:
                print("✓ PreTradeGate appears to have window tracking (900s)")
            else:
                self.add_flaw(
                    category="WINDOW_LIMIT_IMPLEMENTATION",
                    severity=Severity.HIGH,
                    title="PreTradeGate may not have proper window tracking",
                    description="PreTradeGate source does not contain clear window tracking logic. "
                              "Window limits may not be enforced correctly.",
                    location="merid/event_venues/kalshi/order_gate.py",
                    evidence="Source code missing clear window tracking implementation",
                    recommendation="Implement window tracking state (start timestamp, per-agent exposure, total exposure) "
                                  "and enforce 3% per-agent / 5% total limits in PreTradeGate.check()"
                )
                print("⚠ WARNING: PreTradeGate may not have proper window tracking")
                
        except ImportError as e:
            print(f"✗ Could not import PreTradeGate: {e}")
        
        # Check global_risk_guard.py for window limit alignment
        try:
            from merid.guards.global_risk_guard import GlobalRiskGuard
            print("✓ Found GlobalRiskGuard (deprecated)")
            
            guard_source = inspect.getsource(GlobalRiskGuard)
            
            # Check if it uses cycle risk caps (should align with window limits)
            if "max_cycle_risk_pct" in guard_source:
                print("✓ GlobalRiskGuard has max_cycle_risk_pct")
                
                # Check default value
                if "0.05" in guard_source or "5%" in guard_source:
                    print("  - Default appears to be 5% (matches total venue window limit)")
                else:
                    self.add_flaw(
                        category="WINDOW_LIMIT_IMPLEMENTATION",
                        severity=Severity.HIGH,
                        title="GlobalRiskGuard cycle risk cap may not match window limits",
                        description="GlobalRiskGuard max_cycle_risk_pct default may not match expected 5% total venue window limit.",
                        location="merid/guards/global_risk_guard.py",
                        evidence="Default value does not appear to be 5%",
                        recommendation="Align max_cycle_risk_pct with total venue window limit (5%) or remove deprecated guard"
                    )
                    print("  ⚠ WARNING: Default may not match 5% window limit")
            
        except ImportError as e:
            print(f"✗ Could not import GlobalRiskGuard: {e}")
        
        # Check profile YAML for window limit configuration
        profile_path = self.workspace_root / "config/profiles/kalshi_crypto_15m_v2.yaml"
        if profile_path.exists():
            profile_content = profile_path.read_text(encoding='utf-8', errors='ignore')
            
            if "per_window_risk_pct" in profile_content or "window" in profile_content.lower():
                print("✓ Profile YAML appears to have window limit configuration")
                
                if "0.03" in profile_content or "3%" in profile_content:
                    print("  - Profile has 3% per-agent window limit")
                if "0.05" in profile_content or "5%" in profile_content:
                    print("  - Profile has 5% total venue window limit")
            else:
                self.add_flaw(
                    category="WINDOW_LIMIT_IMPLEMENTATION",
                    severity=Severity.HIGH,
                    title="Profile YAML missing window limit configuration",
                    description="Profile YAML does not contain window limit configuration. "
                              "Window limits may not be configured correctly.",
                    location="config/profiles/kalshi_crypto_15m_v2.yaml",
                    evidence="YAML missing per_window_risk_pct or similar configuration",
                    recommendation="Add window limit configuration to profile YAML: "
                                  "guardrails_per_window_risk_pct: 0.03, guardrails_total_venue_risk_pct: 0.05"
                )
                print("⚠ WARNING: Profile YAML missing window limit configuration")
    
    def check_exit_system_gaps(self):
        """Check exit system communication with risk guards."""
        print("\n" + "="*80)
        print("CHECKING EXIT SYSTEM GAPS")
        print("="*80)
        
        # Check position_monitor.py for exit logic
        try:
            from merid.position_management.position_monitor import PositionMonitor
            print("✓ Found PositionMonitor")
            
            monitor_source = inspect.getsource(PositionMonitor)
            
            # Check for exit intent emission
            if "_emit_exit_intent" in monitor_source:
                print("✓ PositionMonitor has exit intent emission")
            else:
                self.add_flaw(
                    category="EXIT_SYSTEM_GAP",
                    severity=Severity.HIGH,
                    title="PositionMonitor missing exit intent emission",
                    description="PositionMonitor does not have _emit_exit_intent method. "
                              "Exit events may not be communicated to risk guards.",
                    location="merid/position_management/position_monitor.py",
                    evidence="Source code missing _emit_exit_intent method",
                    recommendation="Implement exit intent emission to communicate position closures to risk guards"
                )
                print("⚠ WARNING: PositionMonitor missing exit intent emission")
            
            # Check if exit intents communicate with risk guards to release window capacity
            if "window" in monitor_source.lower() and "capacity" in monitor_source.lower():
                print("✓ PositionMonitor appears to communicate window capacity release")
            else:
                self.add_flaw(
                    category="EXIT_SYSTEM_GAP",
                    severity=Severity.CRITICAL,
                    title="Exit system may not release window capacity",
                    description="PositionMonitor exit logic does not appear to communicate with risk guards "
                              "to release window capacity when positions close. This prevents re-entry after exits.",
                    location="merid/position_management/position_monitor.py",
                    evidence="Source code missing window capacity release logic",
                    recommendation="When position closes (via trailing stop, ratchet, 99c exit), "
                                  "notify risk guards to reduce window exposure and allow re-entry"
                )
                print("✗ CRITICAL: Exit system may not release window capacity")
                
        except ImportError as e:
            print(f"✗ Could not import PositionMonitor: {e}")
        
        # Check exit_policy.py for exit precedence
        try:
            from merid.position_management.exit_policy import ExitReason
            print("✓ Found ExitReason enum")
            
            # Check for documented precedence
            if hasattr(ExitReason, '__doc__') and ExitReason.__doc__:
                if "precedence" in ExitReason.__doc__.lower():
                    print("✓ ExitReason has documented precedence order")
                else:
                    self.add_flaw(
                        category="EXIT_SYSTEM_GAP",
                        severity=Severity.MEDIUM,
                        title="ExitReason precedence not documented",
                        description="ExitReason enum does not have documented precedence order. "
                                  "Exit logic may have inconsistent priority.",
                        location="merid/position_management/exit_policy.py",
                        evidence="ExitReason docstring missing precedence documentation",
                        recommendation="Document exit precedence order in ExitReason docstring and ensure implementation matches"
                    )
                    print("⚠ WARNING: ExitReason precedence not documented")
            
            # Check for EXTREME_PROFIT (99c exit)
            if hasattr(ExitReason, 'EXTREME_PROFIT'):
                print("✓ ExitReason has EXTREME_PROFIT (99c exit)")
            else:
                self.add_flaw(
                    category="EXIT_SYSTEM_GAP",
                    severity=Severity.HIGH,
                    title="ExitReason missing EXTREME_PROFIT",
                    description="ExitReason enum does not have EXTREME_PROFIT. "
                              "99c guaranteed win exit may not be implemented.",
                    location="merid/position_management/exit_policy.py",
                    evidence="ExitReason enum missing EXTREME_PROFIT attribute",
                    recommendation="Add EXTREME_PROFIT to ExitReason enum and implement 99c exit logic"
                )
                print("⚠ WARNING: ExitReason missing EXTREME_PROFIT")
                
        except ImportError as e:
            print(f"✗ Could not import ExitReason: {e}")
    
    def check_recording_mechanisms(self):
        """Check recording mechanism consistency across execution paths."""
        print("\n" + "="*80)
        print("CHECKING RECORDING MECHANISM CONSISTENCY")
        print("="*80)
        
        # Check order_gate.py for record_price_execution
        try:
            from merid.event_venues.kalshi.order_gate import IdempotentOrderStore
            print("✓ Found IdempotentOrderStore")
            
            store_source = inspect.getsource(IdempotentOrderStore)
            
            if "record_price_execution" in store_source:
                print("✓ IdempotentOrderStore has record_price_execution method")
            else:
                self.add_flaw(
                    category="RECORDING_GAP",
                    severity=Severity.HIGH,
                    title="IdempotentOrderStore missing record_price_execution",
                    description="IdempotentOrderStore does not have record_price_execution method. "
                              "Price execution history may not be tracked for repeat prevention.",
                    location="merid/event_venues/kalshi/order_gate.py",
                    evidence="Source code missing record_price_execution method",
                    recommendation="Implement record_price_execution to track price execution history and prevent repeat executions"
                )
                print("⚠ WARNING: IdempotentOrderStore missing record_price_execution")
            
            # Check for price repeat prevention
            if "check_price_repeat" in store_source:
                print("✓ IdempotentOrderStore has check_price_repeat method")
            else:
                self.add_flaw(
                    category="RECORDING_GAP",
                    severity=Severity.HIGH,
                    title="IdempotentOrderStore missing check_price_repeat",
                    description="IdempotentOrderStore does not have check_price_repeat method. "
                              "Agents may execute same price multiple times (over-trading risk).",
                    location="merid/event_venues/kalshi/order_gate.py",
                    evidence="Source code missing check_price_repeat method",
                    recommendation="Implement check_price_repeat to prevent repeat price execution within 15-minute window"
                )
                print("⚠ WARNING: IdempotentOrderStore missing check_price_repeat")
                
        except ImportError as e:
            print(f"✗ Could not import IdempotentOrderStore: {e}")
        
        # Check global_risk_guard.py for record_fill
        try:
            from merid.guards.global_risk_guard import GlobalRiskGuard
            print("✓ Found GlobalRiskGuard (deprecated)")
            
            guard_source = inspect.getsource(GlobalRiskGuard)
            
            if "record_fill" in guard_source:
                print("✓ GlobalRiskGuard has record_fill method")
            else:
                self.add_flaw(
                    category="RECORDING_GAP",
                    severity=Severity.HIGH,
                    title="GlobalRiskGuard missing record_fill",
                    description="GlobalRiskGuard does not have record_fill method. "
                              "Fills may not be recorded to release cycle capacity.",
                    location="merid/guards/global_risk_guard.py",
                    evidence="Source code missing record_fill method",
                    recommendation="Implement record_fill to track fills and release cycle capacity for window limit enforcement"
                )
                print("⚠ WARNING: GlobalRiskGuard missing record_fill")
                
        except ImportError as e:
            print(f"✗ Could not import GlobalRiskGuard: {e}")
        
        # Check order_router.py for recording calls
        router_path = self.workspace_root / "merid/event_venues/kalshi/order_router.py"
        if router_path.exists():
            router_content = router_path.read_text(encoding='utf-8', errors='ignore')
            
            if "record_price_execution" in router_content:
                print("✓ order_router.py calls record_price_execution")
            else:
                self.add_flaw(
                    category="RECORDING_GAP",
                    severity=Severity.HIGH,
                    title="order_router.py does not call record_price_execution",
                    description="order_router.py does not call record_price_execution after fills. "
                              "Price execution history may not be updated.",
                    location="merid/event_venues/kalshi/order_router.py",
                    evidence="Source code missing record_price_execution call",
                    recommendation="Add record_price_execution call after successful order execution"
                )
                print("⚠ WARNING: order_router.py does not call record_price_execution")
            
            if "record_fill" in router_content:
                print("✓ order_router.py calls record_fill")
            else:
                self.add_flaw(
                    category="RECORDING_GAP",
                    severity=Severity.HIGH,
                    title="order_router.py does not call record_fill",
                    description="order_router.py does not call record_fill after fills. "
                              "Cycle capacity may not be released for window limit enforcement.",
                    location="merid/event_venues/kalshi/order_router.py",
                    evidence="Source code missing record_fill call",
                    recommendation="Add record_fill call after successful order execution to release cycle capacity"
                )
                print("⚠ WARNING: order_router.py does not call record_fill")
    
    def check_legacy_contamination(self):
        """Check for legacy vs production code contamination."""
        print("\n" + "="*80)
        print("CHECKING LEGACY VS PRODUCTION CONTAMINATION")
        print("="*80)
        
        # Check if main.py (legacy) is imported by production code
        print("Checking for legacy main.py imports in production code...")
        
        production_files = [
            "web/main_15m_lean.py",
            "merid/loop_15m.py",
            "merid/event_venues/kalshi/client.py"
        ]
        
        for file_path in production_files:
            full_path = self.workspace_root / file_path
            if full_path.exists():
                content = full_path.read_text(encoding='utf-8', errors='ignore')
                
                if "from web.main import" in content or "import web.main" in content:
                    self.add_flaw(
                        category="LEGACY_CONTAMINATION",
                        severity=Severity.CRITICAL,
                        title=f"Production code imports legacy main.py",
                        description=f"File {file_path} imports legacy web.main.py. "
                                  "This creates risk of legacy startup patterns contaminating production.",
                        location=file_path,
                        evidence="File contains 'from web.main import' or 'import web.main'",
                        recommendation="Replace with web.main_15m_lean imports. Ensure all production code uses main_15m_lean.py"
                    )
                    print(f"✗ CRITICAL: {file_path} imports legacy main.py")
                else:
                    print(f"✓ {file_path} does not import legacy main.py")
        
        # Check for legacy venue adapters (limited to specific files to avoid hanging)
        print("\nChecking for legacy venue adapters (limited scan)...")
        legacy_patterns = [
            "legacy_adapter",
            "LegacyAdapter",
            "kalshi_continuous_trader",  # Legacy trading agent
        ]
        
        # Only check key production files instead of recursive scan
        key_files = [
            "web/main_15m_lean.py",
            "merid/loop_15m.py",
            "merid/event_venues/kalshi/order_router.py",
            "merid/event_venues/kalshi/client.py",
            "merid/position_management/position_monitor.py"
        ]
        
        for file_path in key_files:
            full_path = self.workspace_root / file_path
            if full_path.exists():
                try:
                    content = full_path.read_text(encoding='utf-8', errors='ignore')
                    for pattern in legacy_patterns:
                        if pattern in content:
                            self.add_flaw(
                                category="LEGACY_CONTAMINATION",
                                severity=Severity.MEDIUM,
                                title=f"Production file contains legacy pattern: {pattern}",
                                description=f"File {file_path} contains legacy pattern '{pattern}'. "
                                          "May indicate legacy code contamination.",
                                location=file_path,
                                evidence=f"File contains '{pattern}'",
                                recommendation="Review and replace with production equivalents if applicable"
                            )
                            print(f"⚠ WARNING: {file_path} contains legacy pattern '{pattern}'")
                except Exception as e:
                    print(f"Error checking {file_path}: {e}")
    
    def check_end_to_end_gaps(self):
        """Check end-to-end execution-to-exit flow gaps."""
        print("\n" + "="*80)
        print("CHECKING END-TO-END EXECUTION-TO-EXIT FLOW GAPS")
        print("="*80)
        
        # Check if position cache tracks exit events
        try:
            from merid.event_venues.kalshi.position_cache import PositionCache
            print("✓ Found PositionCache")
            
            cache_source = inspect.getsource(PositionCache)
            
            # Check for position close tracking
            if "close" in cache_source.lower() or "exit" in cache_source.lower():
                print("✓ PositionCache appears to track position close/exit events")
            else:
                self.add_flaw(
                    category="E2E_FLOW_GAP",
                    severity=Severity.HIGH,
                    title="PositionCache may not track position close events",
                    description="PositionCache may not track position close events. "
                              "Window exposure may not be reduced when positions exit.",
                    location="merid/event_venues/kalshi/position_cache.py",
                    evidence="Source code missing close/exit event tracking",
                    recommendation="Implement position close event tracking to notify risk guards of exposure reduction"
                )
                print("⚠ WARNING: PositionCache may not track position close events")
                
        except ImportError as e:
            print(f"✗ Could not import PositionCache: {e}")
        
        # Check fills_ledger for P&L tracking
        try:
            from merid.event_venues.kalshi.fills_ledger import FillsLedger
            print("✓ Found FillsLedger")
            
            ledger_source = inspect.getsource(FillsLedger)
            
            # Check for daily P&L tracking
            if "daily" in ledger_source.lower() and "pnl" in ledger_source.lower():
                print("✓ FillsLedger tracks daily P&L")
            else:
                self.add_flaw(
                    category="E2E_FLOW_GAP",
                    severity=Severity.MEDIUM,
                    title="FillsLedger may not track daily P&L",
                    description="FillsLedger may not track daily P&L. "
                              "Risk guards may not have accurate P&L data for daily loss limits.",
                    location="merid/event_venues/kalshi/fills_ledger.py",
                    evidence="Source code missing daily P&L tracking",
                    recommendation="Implement daily P&L tracking in FillsLedger for risk guard integration"
                )
                print("⚠ WARNING: FillsLedger may not track daily P&L")
                
        except ImportError as e:
            print(f"✗ Could not import FillsLedger: {e}")
        
        # Check for circular dependencies between execution and exit
        print("\nChecking for circular dependencies...")
        
        # Check if position_monitor imports order_router
        monitor_path = self.workspace_root / "merid/position_management/position_monitor.py"
        if monitor_path.exists():
            monitor_content = monitor_path.read_text(encoding='utf-8', errors='ignore')
            
            if "order_router" in monitor_content:
                self.add_flaw(
                    category="E2E_FLOW_GAP",
                    severity=Severity.MEDIUM,
                    title="position_monitor imports order_router (circular dependency risk)",
                    description="position_monitor.py imports order_router. This may create circular dependencies "
                              "between execution and exit systems.",
                    location="merid/position_management/position_monitor.py",
                    evidence="File contains 'order_router' import",
                    recommendation="Refactor to use callback interfaces instead of direct imports to break circular dependencies"
                )
                print("⚠ WARNING: position_monitor imports order_router (circular dependency risk)")
    
    def generate_report(self):
        """Generate a comprehensive report of all discovered flaws."""
        print("\n" + "="*80)
        print("FLAW EXPOSURE REPORT")
        print("="*80)
        
        # Group flaws by category
        flaws_by_category: Dict[str, List[Flaw]] = {}
        for flaw in self.flaws:
            if flaw.category not in flaws_by_category:
                flaws_by_category[flaw.category] = []
            flaws_by_category[flaw.category].append(flaw)
        
        # Print summary
        total_flaws = len(self.flaws)
        critical_flaws = len([f for f in self.flaws if f.severity == Severity.CRITICAL])
        high_flaws = len([f for f in self.flaws if f.severity == Severity.HIGH])
        medium_flaws = len([f for f in self.flaws if f.severity == Severity.MEDIUM])
        low_flaws = len([f for f in self.flaws if f.severity == Severity.LOW])
        
        print(f"\nSUMMARY:")
        print(f"  Total flaws: {total_flaws}")
        print(f"  CRITICAL: {critical_flaws}")
        print(f"  HIGH: {high_flaws}")
        print(f"  MEDIUM: {medium_flaws}")
        print(f"  LOW: {low_flaws}")
        
        # Print flaws by category
        for category, flaws in flaws_by_category.items():
            print(f"\n{'='*80}")
            print(f"{category} ({len(flaws)} flaws)")
            print("="*80)
            
            for flaw in flaws:
                print(f"\n[{flaw.severity.value}] {flaw.title}")
                print(f"  Location: {flaw.location}")
                print(f"  Description: {flaw.description}")
                print(f"  Evidence: {flaw.evidence}")
                print(f"  Recommendation: {flaw.recommendation}")
        
        # Print critical flaws first
        print(f"\n{'='*80}")
        print("CRITICAL FLAWS (Immediate Action Required)")
        print("="*80)
        
        critical_flaws_list = [f for f in self.flaws if f.severity == Severity.CRITICAL]
        if critical_flaws_list:
            for flaw in critical_flaws_list:
                print(f"\n• {flaw.title}")
                print(f"  Location: {flaw.location}")
                print(f"  Recommendation: {flaw.recommendation}")
        else:
            print("\n✓ No critical flaws found")
        
        # Save report to file
        report_path = self.workspace_root / "trading_flaw_exposure_report.txt"
        with open(report_path, 'w') as f:
            f.write("TRADING RISK AND EXECUTION FLAW EXPOSURE REPORT\n")
            f.write("="*80 + "\n\n")
            
            f.write(f"SUMMARY:\n")
            f.write(f"  Total flaws: {total_flaws}\n")
            f.write(f"  CRITICAL: {critical_flaws}\n")
            f.write(f"  HIGH: {high_flaws}\n")
            f.write(f"  MEDIUM: {medium_flaws}\n")
            f.write(f"  LOW: {low_flaws}\n\n")
            
            for category, flaws in flaws_by_category.items():
                f.write(f"\n{'='*80}\n")
                f.write(f"{category} ({len(flaws)} flaws)\n")
                f.write("="*80 + "\n")
                
                for flaw in flaws:
                    f.write(f"\n[{flaw.severity.value}] {flaw.title}\n")
                    f.write(f"  Location: {flaw.location}\n")
                    f.write(f"  Description: {flaw.description}\n")
                    f.write(f"  Evidence: {flaw.evidence}\n")
                    f.write(f"  Recommendation: {flaw.recommendation}\n")
        
        print(f"\n✓ Report saved to: {report_path}")
    
    def run_all_checks(self):
        """Run all flaw exposure checks."""
        print("="*80)
        print("TRADING RISK AND EXECUTION FLAW EXPOSURE")
        print("="*80)
        print("This script systematically checks for flaws in the trading system.")
        print("Checks include:")
        print("  1. Multiple competing risk guard systems")
        print("  2. Window-based risk limit implementation gaps")
        print("  3. Exit system communication gaps")
        print("  4. Recording mechanism inconsistencies")
        print("  5. Legacy vs production code contamination")
        print("  6. End-to-end execution-to-exit flow gaps")
        
        self.check_multiple_risk_guards()
        self.check_window_limit_implementation()
        self.check_exit_system_gaps()
        self.check_recording_mechanisms()
        self.check_legacy_contamination()
        self.check_end_to_end_gaps()
        
        self.generate_report()


def main():
    """Main entry point."""
    exposure = FlawExposure()
    exposure.run_all_checks()


if __name__ == "__main__":
    main()
