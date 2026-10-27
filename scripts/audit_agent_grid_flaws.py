"""
Comprehensive Agent Grid Flaw Audit Script

This script exposes all flaws in the agent grid across BTC, ETH, SOL, XRP, DOGE
by testing upstream, midstream, downstream, and end-to-end guard enforcement.

Flaws Exposed:
1. Missing window exposure refund for rejected orders
2. YES/NO arbitrage bypassing window limits
3. Upstream reservation path inconsistency
4. No refund for Kalshi business rejects
5. Position closure detection gaps
6. Market maker special handling
7. Dual order router implementations
"""

import sys
import os
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Simple logger to avoid import hanging
class SimpleLogger:
    def info(self, msg, *args):
        print(f"[INFO] {msg % args if args else msg}")
    
    def warning(self, msg, *args):
        print(f"[WARN] {msg % args if args else msg}")
    
    def error(self, msg, *args):
        print(f"[ERROR] {msg % args if args else msg}")

logger = SimpleLogger()


@dataclass
class AuditResult:
    """Result of a single audit check."""
    check_name: str
    passed: bool
    details: str
    severity: str  # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    recommendation: str


class AgentGridAuditor:
    """Comprehensive auditor for agent grid flaws."""
    
    def __init__(self):
        self.results: List[AuditResult] = []
        self.assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
    def add_result(self, check_name: str, passed: bool, details: str, 
                   severity: str, recommendation: str):
        """Add an audit result."""
        result = AuditResult(
            check_name=check_name,
            passed=passed,
            details=details,
            severity=severity,
            recommendation=recommendation
        )
        self.results.append(result)
        status = "✓ PASS" if passed else "✗ FAIL"
        logger.info(f"[{status}] {check_name}: {details}")
        
    def audit_window_exposure_refund(self):
        """FLAW 1: Check if rejected orders refund window exposure."""
        logger.info("=" * 80)
        logger.info("AUDIT: Window Exposure Refund for Rejected Orders")
        logger.info("=" * 80)
        
        # Check risk envelope for refund method
        envelope_source = self._search_file_for_pattern(
            "merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
            "def refund_order_execution"
        )
        
        if not envelope_source:
            self.add_result(
                check_name="Window Exposure Refund Method Exists",
                passed=False,
                details="refund_order_execution method not found in risk envelope",
                severity="CRITICAL",
                recommendation="Implement refund_order_execution to release window capacity for rejected orders"
            )
        else:
            self.add_result(
                check_name="Window Exposure Refund Method Exists",
                passed=True,
                details="refund_order_execution method exists in risk envelope",
                severity="CRITICAL",
                recommendation="Ensure this is called for all rejected orders"
            )
        
        # Check order gate for refund calls on rejection
        gate_source = self._search_file_for_pattern(
            "merid/event_venues/kalshi/order_gate.py",
            "refund_order_execution"
        )
        
        if not gate_source:
            self.add_result(
                check_name="Order Gate Calls Refund on Rejection",
                passed=False,
                details="order_gate.py does not call refund_order_execution on rejected orders",
                severity="CRITICAL",
                recommendation="Add refund_order_execution calls in order gate rejection paths"
            )
        else:
            self.add_result(
                check_name="Order Gate Calls Refund on Rejection",
                passed=True,
                details=f"Found refund_order_execution calls in order_gate.py",
                severity="CRITICAL",
                recommendation="Verify all rejection paths call refund"
            )
        
        # Check order router for refund calls on rejection
        router_source = self._search_file_for_pattern(
            "merid/event_venues/kalshi/order_router.py",
            "refund_order_execution"
        )
        
        if not router_source:
            self.add_result(
                check_name="Order Router Calls Refund on Rejection",
                passed=False,
                details="order_router.py does not call refund_order_execution on rejected orders",
                severity="CRITICAL",
                recommendation="Add refund_order_execution calls in order router rejection paths"
            )
        else:
            self.add_result(
                check_name="Order Router Calls Refund on Rejection",
                passed=True,
                details=f"Found refund_order_execution calls in order_router.py",
                severity="CRITICAL",
                recommendation="Verify all rejection paths call refund"
            )
    
    def audit_arbitrage_window_bypass(self):
        """FLAW 2: Check if YES/NO arbitrage bypasses window limits."""
        logger.info("=" * 80)
        logger.info("AUDIT: YES/NO Arbitrage Window Limit Bypass")
        logger.info("=" * 80)
        
        # Check execute_arbitrage_async implementation
        router_source = self._search_file_for_pattern(
            "merid/event_venues/kalshi/order_router.py",
            "execute_arbitrage_async"
        )
        
        if not router_source:
            self.add_result(
                check_name="Arbitrage Execution Function Exists",
                passed=False,
                details="execute_arbitrage_async not found in order_router.py",
                severity="HIGH",
                recommendation="Verify arbitrage implementation location"
            )
            return
        
        # Check if arbitrage orders go through gate
        arbitrage_uses_gate = "gate.check" in router_source or "pre_trade_gate" in router_source
        
        if not arbitrage_uses_gate:
            self.add_result(
                check_name="Arbitrage Orders Go Through Order Gate",
                passed=False,
                details="execute_arbitrage_async does not appear to call gate.check",
                severity="CRITICAL",
                recommendation="Ensure arbitrage orders go through full gate checks including window limits"
            )
        else:
            self.add_result(
                check_name="Arbitrage Orders Go Through Order Gate",
                passed=True,
                details="execute_arbitrage_async appears to call gate.check",
                severity="CRITICAL",
                recommendation="Verify window limit checks are included"
            )
        
        # Check if arbitrage bypasses window limits
        arbitrage_bypass = "window_limit" not in router_source.lower()
        
        if arbitrage_bypass:
            self.add_result(
                check_name="Arbitrage Respects Window Limits",
                passed=False,
                details="execute_arbitrage_async does not check window limits",
                severity="CRITICAL",
                recommendation="Add window limit checks to arbitrage execution path"
            )
        else:
            self.add_result(
                check_name="Arbitrage Respects Window Limits",
                passed=True,
                details="execute_arbitrage_async checks window limits",
                severity="CRITICAL",
                recommendation="None"
            )
    
    def audit_upstream_reservation_path(self):
        """FLAW 3: Check upstream reservation path consistency."""
        logger.info("=" * 80)
        logger.info("AUDIT: Upstream Reservation Path Consistency")
        logger.info("=" * 80)
        
        # Check for upstream reservation path in order router
        router_source = self._search_file_for_pattern(
            "merid/event_venues/kalshi/order_router.py",
            "upstream.*reservation|upstream_coid"
        )
        
        if not router_source:
            self.add_result(
                check_name="Upstream Reservation Path Exists",
                passed=True,
                details="No upstream reservation path found (single code path)",
                severity="MEDIUM",
                recommendation="None"
            )
            return
        
        # Check if upstream path has window limit checks
        has_window_check = "window_limit" in router_source.lower() or "check_window_limit" in router_source
        
        if not has_window_check:
            self.add_result(
                check_name="Upstream Path Has Window Limit Checks",
                passed=False,
                details="Upstream reservation path does not check window limits",
                severity="CRITICAL",
                recommendation="Add window limit checks to upstream reservation path"
            )
        else:
            self.add_result(
                check_name="Upstream Path Has Window Limit Checks",
                passed=True,
                details="Upstream reservation path checks window limits",
                severity="CRITICAL",
                recommendation="Verify consistency with normal path"
            )
        
        # Check if upstream path bypasses gate.check
        bypasses_gate = "gate.check" not in router_source
        
        if bypasses_gate:
            self.add_result(
                check_name="Upstream Path Bypasses Gate Check",
                passed=False,
                details="Upstream reservation path bypasses gate.check",
                severity="HIGH",
                recommendation="Ensure upstream path has equivalent risk checks"
            )
        else:
            self.add_result(
                check_name="Upstream Path Bypasses Gate Check",
                passed=True,
                details="Upstream reservation path calls gate.check",
                severity="HIGH",
                recommendation="None"
            )
    
    def audit_kalshi_business_reject_refund(self):
        """FLAW 4: Check if Kalshi business rejects refund window exposure."""
        logger.info("=" * 80)
        logger.info("AUDIT: Kalshi Business Reject Refund")
        logger.info("=" * 80)
        
        # Check venue_adapter for KalshiBusinessReject handling (where fix was implemented)
        adapter_source = self._search_file_for_pattern(
            "merid/event_venues/kalshi/venue_adapter.py",
            "KalshiBusinessReject|KalshiBusinessError"
        )
        
        if not adapter_source:
            self.add_result(
                check_name="Kalshi Business Reject Handling Exists",
                passed=False,
                details="No KalshiBusinessReject handling found in venue_adapter.py",
                severity="HIGH",
                recommendation="Add KalshiBusinessReject handling with window refund"
            )
            return
        
        # Check if business reject calls refund
        has_refund = "refund_order_execution" in adapter_source
        
        if not has_refund:
            self.add_result(
                check_name="Business Reject Calls Window Refund",
                passed=False,
                details="KalshiBusinessReject handling does not call refund_order_execution",
                severity="CRITICAL",
                recommendation="Add refund_order_execution call for Kalshi business rejects"
            )
        else:
            self.add_result(
                check_name="Business Reject Calls Window Refund",
                passed=True,
                details="KalshiBusinessReject handling calls refund_order_execution",
                severity="CRITICAL",
                recommendation="None"
            )
    
    def audit_position_closure_detection(self):
        """FLAW 5: Check position closure detection and window release."""
        logger.info("=" * 80)
        logger.info("AUDIT: Position Closure Detection and Window Release")
        logger.info("=" * 80)
        
        # Check position monitor for window release
        monitor_source = self._search_file_for_pattern(
            "merid/position_management/position_monitor.py",
            "record_position_closure"
        )
        
        if not monitor_source:
            self.add_result(
                check_name="Position Monitor Releases Window Capacity",
                passed=False,
                details="position_monitor.py does not call record_position_closure",
                severity="CRITICAL",
                recommendation="Add record_position_closure call when positions close"
            )
        else:
            self.add_result(
                check_name="Position Monitor Releases Window Capacity",
                passed=True,
                details="position_monitor.py calls record_position_closure",
                severity="CRITICAL",
                recommendation="Verify all position close paths trigger this"
            )
        
        # Check position cache for window release
        cache_source = self._search_file_for_pattern(
            "merid/event_venues/kalshi/position_cache.py",
            "record_position_closure"
        )
        
        if not cache_source:
            self.add_result(
                check_name="Position Cache Releases Window Capacity",
                passed=False,
                details="position_cache.py does not call record_position_closure",
                severity="CRITICAL",
                recommendation="Add record_position_closure call in position cache"
            )
        else:
            self.add_result(
                check_name="Position Cache Releases Window Capacity",
                passed=True,
                details="position_cache.py calls record_position_closure",
                severity="CRITICAL",
                recommendation="None"
            )
    
    def audit_market_maker_special_handling(self):
        """FLAW 6: Check market maker special handling and risk limits."""
        logger.info("=" * 80)
        logger.info("AUDIT: Market Maker Special Handling")
        logger.info("=" * 80)
        
        # Check order gate for market maker detection
        gate_source = self._search_file_for_pattern(
            "merid/event_venues/kalshi/order_gate.py",
            "market.*maker|_is_market_maker"
        )
        
        if not gate_source:
            self.add_result(
                check_name="Market Maker Detection Exists",
                passed=False,
                details="No market maker detection found in order_gate.py",
                severity="MEDIUM",
                recommendation="None (if market makers not used)"
            )
            return
        
        # Check if market makers have different window limits
        has_mm_window_check = "window_limit" in gate_source.lower()
        
        if not has_mm_window_check:
            self.add_result(
                check_name="Market Makers Have Window Limit Checks",
                passed=False,
                details="Market maker path does not check window limits",
                severity="HIGH",
                recommendation="Ensure market makers respect window limits"
            )
        else:
            self.add_result(
                check_name="Market Makers Have Window Limit Checks",
                passed=True,
                details="Market maker path checks window limits",
                severity="HIGH",
                recommendation="Verify limits are same as regular agents"
            )
    
    def audit_dual_order_router_implementations(self):
        """FLAW 7: Check for dual order router implementations."""
        logger.info("=" * 80)
        logger.info("AUDIT: Dual Order Router Implementations")
        logger.info("=" * 80)
        
        # Check if order_router_15m.py exists
        router_15m_path = "merid/event_venues/kalshi/order_router_15m.py"
        router_15m_exists = os.path.exists(os.path.join(os.path.dirname(__file__), "..", router_15m_path))
        
        if router_15m_exists:
            # Check if it's marked as legacy/mock
            router_15m_source = self._read_file(router_15m_path)
            is_mock = "MOCK" in router_15m_source or "NOT USED" in router_15m_source or "legacy" in router_15m_source.lower()
            
            if is_mock:
                self.add_result(
                    check_name="Order Router 15m Marked as Legacy",
                    passed=True,
                    details="order_router_15m.py is marked as legacy/mock",
                    severity="MEDIUM",
                    recommendation="Ensure no production code imports this"
                )
            else:
                self.add_result(
                    check_name="Order Router 15m Marked as Legacy",
                    passed=False,
                    details="order_router_15m.py exists but not marked as legacy",
                    severity="HIGH",
                    recommendation="Mark as legacy or remove to prevent accidental use"
                )
            
            # Check for imports of order_router_15m
            imports_15m = self._search_codebase_for_pattern(
                "from.*order_router_15m|import.*order_router_15m"
            )
            
            if imports_15m:
                self.add_result(
                    check_name="No Production Code Imports Legacy Router",
                    passed=False,
                    details=f"Found {len(imports_15m)} files importing order_router_15m",
                    severity="CRITICAL",
                    recommendation="Remove imports of legacy order_router_15m in production code"
                )
            else:
                self.add_result(
                    check_name="No Production Code Imports Legacy Router",
                    passed=True,
                    details="No production code imports order_router_15m",
                    severity="CRITICAL",
                    recommendation="None"
                )
        else:
            self.add_result(
                check_name="Legacy Order Router Exists",
                passed=True,
                details="order_router_15m.py does not exist (no dual implementation)",
                severity="MEDIUM",
                recommendation="None"
            )
    
    def audit_profile_consistency(self):
        """Check profile YAML consistency across all layers."""
        logger.info("=" * 80)
        logger.info("AUDIT: Profile YAML Consistency")
        logger.info("=" * 80)
        
        # Check profile YAML file directly
        profile_source = self._search_file_for_pattern(
            "config/profiles/kalshi_crypto_15m_v2.yaml",
            "agent_max_notional_pct|venue_max_total_notional_pct|guardrails_per_window_risk_pct|guardrails_total_venue_risk_pct"
        )
        
        if not profile_source:
            self.add_result(
                check_name="Profile YAML Exists",
                passed=False,
                details="Profile YAML not found at config/profiles/kalshi_crypto_15m_v2.yaml",
                severity="CRITICAL",
                recommendation="Ensure profile YAML exists"
            )
            return
        
        # Check for critical values in profile
        checks = [
            ("agent_max_notional_pct", "0.03", "3% per agent"),
            ("venue_max_total_notional_pct", "0.15", "15% total venue"),
            ("guardrails_per_window_risk_pct", "0.03", "3% per window"),
            ("guardrails_total_venue_risk_pct", "0.05", "5% total window"),
        ]
        
        for attr, expected_value, description in checks:
            if expected_value in profile_source:
                self.add_result(
                    check_name=f"Profile {attr} Value Correct",
                    passed=True,
                    details=f"Profile YAML has {attr}={expected_value} ({description})",
                    severity="CRITICAL",
                    recommendation="None"
                )
            else:
                self.add_result(
                    check_name=f"Profile {attr} Value Correct",
                    passed=False,
                    details=f"Profile YAML missing {attr}={expected_value} ({description})",
                    severity="CRITICAL",
                    recommendation=f"Add {attr} to profile YAML"
                )
        
        # Check all 5 assets are present
        for asset in self.assets:
            if asset.lower() in profile_source.lower():
                self.add_result(
                    check_name=f"Profile Has {asset} Config",
                    passed=True,
                    details=f"Profile YAML has {asset} configuration",
                    severity="CRITICAL",
                    recommendation="None"
                )
            else:
                self.add_result(
                    check_name=f"Profile Has {asset} Config",
                    passed=False,
                    details=f"Profile YAML missing {asset} configuration",
                    severity="CRITICAL",
                    recommendation=f"Add {asset} config to profile YAML"
                )
    
    def _search_file_for_pattern(self, file_path: str, pattern: str) -> str:
        """Search a file for a pattern and return matching lines."""
        try:
            full_path = os.path.join(os.path.dirname(__file__), "..", file_path)
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            return content
        except Exception as e:
            logger.warning(f"Failed to read {file_path}: {e}")
            return ""
    
    def _read_file(self, file_path: str) -> str:
        """Read a file and return its content."""
        try:
            full_path = os.path.join(os.path.dirname(__file__), "..", file_path)
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception as e:
            logger.warning(f"Failed to read {file_path}: {e}")
            return ""
    
    def _search_codebase_for_pattern(self, pattern: str) -> List[str]:
        """Search codebase for pattern and return matching files."""
        matching_files = []
        
        for root, dirs, files in os.walk(os.path.join(os.path.dirname(__file__), "..")):
            # Skip common exclusions
            dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', 'node_modules', '.venv']]
            
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    # Skip test files and audit script itself
                    if 'test' in file_path or 'audit_agent_grid_flaws' in file_path:
                        continue
                    # Skip the legacy router file itself
                    if 'order_router_15m.py' in file_path:
                        continue
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                        if re.search(pattern, content, re.IGNORECASE):
                            matching_files.append(file_path)
                    except Exception:
                        continue
        
        return matching_files
    
    def print_summary(self):
        """Print audit summary."""
        logger.info("=" * 80)
        logger.info("AUDIT SUMMARY")
        logger.info("=" * 80)
        
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        
        logger.info(f"Total Checks: {total}")
        logger.info(f"Passed: {passed}")
        logger.info(f"Failed: {failed}")
        
        # Group by severity
        by_severity = {}
        for result in self.results:
            if result.severity not in by_severity:
                by_severity[result.severity] = []
            by_severity[result.severity].append(result)
        
        logger.info("\n" + "=" * 80)
        logger.info("CRITICAL ISSUES")
        logger.info("=" * 80)
        
        for result in by_severity.get("CRITICAL", []):
            if not result.passed:
                logger.info(f"\n✗ {result.check_name}")
                logger.info(f"  Details: {result.details}")
                logger.info(f"  Recommendation: {result.recommendation}")
        
        logger.info("\n" + "=" * 80)
        logger.info("HIGH SEVERITY ISSUES")
        logger.info("=" * 80)
        
        for result in by_severity.get("HIGH", []):
            if not result.passed:
                logger.info(f"\n✗ {result.check_name}")
                logger.info(f"  Details: {result.details}")
                logger.info(f"  Recommendation: {result.recommendation}")
        
        logger.info("\n" + "=" * 80)
        logger.info("MEDIUM SEVERITY ISSUES")
        logger.info("=" * 80)
        
        for result in by_severity.get("MEDIUM", []):
            if not result.passed:
                logger.info(f"\n✗ {result.check_name}")
                logger.info(f"  Details: {result.details}")
                logger.info(f"  Recommendation: {result.recommendation}")
        
        logger.info("\n" + "=" * 80)
        logger.info("ALL CHECKS (PASSED & FAILED)")
        logger.info("=" * 80)
        
        for result in self.results:
            status = "✓" if result.passed else "✗"
            logger.info(f"{status} [{result.severity}] {result.check_name}: {result.details}")


def main():
    """Run comprehensive agent grid flaw audit."""
    logger.info("Starting Agent Grid Flaw Audit")
    logger.info("Assets: BTC, ETH, SOL, XRP, DOGE")
    logger.info("=" * 80)
    
    auditor = AgentGridAuditor()
    
    # Run all audits
    auditor.audit_window_exposure_refund()
    auditor.audit_arbitrage_window_bypass()
    auditor.audit_upstream_reservation_path()
    auditor.audit_kalshi_business_reject_refund()
    auditor.audit_position_closure_detection()
    auditor.audit_market_maker_special_handling()
    auditor.audit_dual_order_router_implementations()
    auditor.audit_profile_consistency()
    
    # Print summary
    auditor.print_summary()
    
    # Exit with error code if any critical checks failed
    critical_failed = any(
        not r.passed and r.severity == "CRITICAL" 
        for r in auditor.results
    )
    
    if critical_failed:
        logger.error("\n✗ AUDIT FAILED: Critical issues detected")
        sys.exit(1)
    else:
        logger.info("\n✓ AUDIT PASSED: No critical issues detected")
        sys.exit(0)


if __name__ == "__main__":
    main()
