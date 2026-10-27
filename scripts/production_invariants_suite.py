"""
Production Invariants Suite for Daily Log Reconciliation

This script runs a comprehensive suite of invariants against production logs
to detect issues, drift, and misalignments in the live trading system.

Usage::

    python scripts/production_invariants_suite.py --log-dir /path/to/logs --output reports/invariants_report_YYYYMMDD.md
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta
import re
import json

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from merid.validation.edge_probability_invariants import (
    EdgeProbabilityInvariantChecker,
    EdgeProbabilityViolation,
)
from merid.validation.regime_gating_invariants import (
    RegimeGatingInvariantChecker,
    RegimeGatingViolation,
)
from merid.validation.spot_strike_distance_invariants import (
    SpotStrikeDistanceInvariantChecker,
    SpotStrikeDistanceViolation,
)
from merid.validation.canonical_mapping_invariants import (
    CanonicalMappingTable,
    CanonicalMappingViolation,
)
from merid.validation.reconciliation_invariants import (
    ReconciliationInvariantChecker,
    ReconciliationViolation,
    Episode,
)
from merid.validation.config_invariants import (
    ConfigInvariantChecker,
    ConfigViolation,
)


class InvariantSeverity(str, Enum):
    """Severity levels for invariant violations."""
    CRITICAL = "CRITICAL"  # System-breaking, requires immediate action
    HIGH = "HIGH"  # Significant issue, investigate soon
    MEDIUM = "MEDIUM"  # Moderate issue, monitor
    LOW = "LOW"  # Minor issue, track for trends


@dataclass
class InvariantResult:
    """Result of a single invariant check."""
    invariant_name: str
    severity: InvariantSeverity
    is_valid: bool
    violation_type: Optional[str]
    message: str
    context: Dict[str, Any]
    timestamp: datetime
    
    def to_markdown(self) -> str:
        """Convert to markdown format."""
        status = "PASS" if self.is_valid else "FAIL"
        timestamp_str = self.timestamp.strftime("%Y-%m-%d %H:%M:%S") if self.timestamp else "N/A"
        return f"""
### {self.invariant_name} - {status}

- **Severity**: {self.severity.value}
- **Violation Type**: {self.violation_type or "None"}
- **Message**: {self.message}
- **Timestamp**: {timestamp_str}
- **Context**: `{json.dumps(self.context, indent=2)}`
"""


class ProductionInvariantsSuite:
    """Comprehensive production invariants suite for daily reconciliation."""
    
    def __init__(self, log_dir: str):
        self.log_dir = Path(log_dir)
        self.results: List[InvariantResult] = []
        self.start_time = datetime.now()
    
    def run_all_invariants(self) -> List[InvariantResult]:
        """Run all production invariants."""
        print(f"Running production invariants suite on {self.log_dir}...")
        
        # Run edge-probability invariants
        self._run_edge_probability_invariants()
        
        # Run regime gating invariants
        self._run_regime_gating_invariants()
        
        # Run spot-strike distance invariants
        self._run_spot_strike_distance_invariants()
        
        # Run canonical mapping invariants
        self._run_canonical_mapping_invariants()
        
        # Run reconciliation invariants
        self._run_reconciliation_invariants()
        
        # Run config invariants
        self._run_config_invariants()
        
        return self.results
    
    def _run_edge_probability_invariants(self):
        """Run edge-probability consistency invariants."""
        print("Running edge-probability invariants...")
        
        checker = EdgeProbabilityInvariantChecker()
        
        # Parse log files for edge/probability data
        log_files = self._find_log_files("edge_probability")
        
        for log_file in log_files:
            try:
                with open(log_file, 'r') as f:
                    for line in f:
                        # Parse edge/probability data from log line
                        data = self._parse_edge_probability_log(line)
                        if data:
                            # Check edge sign consistency
                            result = checker.check_edge_sign_consistency(
                                data["p_model"],
                                data["edge"],
                                data["chosen_side"],
                            )
                            
                            severity = self._determine_severity(
                                result.is_valid,
                                EdgeProbabilityViolation(result.violation_type.value) if result.violation_type else None,
                            )
                            
                            self.results.append(InvariantResult(
                                invariant_name="Edge Probability Consistency",
                                severity=severity,
                                is_valid=result.is_valid,
                                violation_type=result.violation_type.value if result.violation_type else None,
                                message=result.message,
                                context=result.context,
                                timestamp=datetime.now(),
                            ))
            
            except Exception as e:
                print(f"Error processing {log_file}: {e}")
    
    def _run_regime_gating_invariants(self):
        """Run regime gating invariants."""
        print("Running regime gating invariants...")
        
        checker = RegimeGatingInvariantChecker()
        
        log_files = self._find_log_files("regime_gating")
        
        for log_file in log_files:
            try:
                with open(log_file, 'r') as f:
                    for line in f:
                        data = self._parse_regime_gating_log(line)
                        if data:
                            # Check volatility gating
                            result = checker.check_volatility_gating(
                                data["volatility"],
                                data["volatility_flag"],
                                data["position_size"],
                                data["strategy_disabled"],
                                data["trade_emitted"],
                            )
                            
                            severity = self._determine_severity(
                                result.is_valid,
                                RegimeGatingViolation(result.violation_type.value) if result.violation_type else None,
                            )
                            
                            self.results.append(InvariantResult(
                                invariant_name="Regime Gating: Volatility",
                                severity=severity,
                                is_valid=result.is_valid,
                                violation_type=result.violation_type.value if result.violation_type else None,
                                message=result.message,
                                context=result.context,
                                timestamp=datetime.now(),
                            ))
            
            except Exception as e:
                print(f"Error processing {log_file}: {e}")
    
    def _run_spot_strike_distance_invariants(self):
        """Run spot-strike distance invariants."""
        print("Running spot-strike distance invariants...")
        
        checker = SpotStrikeDistanceInvariantChecker()
        
        log_files = self._find_log_files("spot_strike")
        
        for log_file in log_files:
            try:
                with open(log_file, 'r') as f:
                    for line in f:
                        data = self._parse_spot_strike_log(line)
                        if data:
                            # Check spot-strike distance
                            result = checker.check_spot_strike_distance(
                                data["spot_price"],
                                data["strike_price"],
                                data["trade_emitted"],
                            )
                            
                            severity = self._determine_severity(
                                result.is_valid,
                                SpotStrikeDistanceViolation(result.violation_type.value) if result.violation_type else None,
                            )
                            
                            self.results.append(InvariantResult(
                                invariant_name="Spot-Strike Distance",
                                severity=severity,
                                is_valid=result.is_valid,
                                violation_type=result.violation_type.value if result.violation_type else None,
                                message=result.message,
                                context=result.context,
                                timestamp=datetime.now(),
                            ))
            
            except Exception as e:
                print(f"Error processing {log_file}: {e}")
    
    def _run_canonical_mapping_invariants(self):
        """Run canonical mapping invariants."""
        print("Running canonical mapping invariants...")
        
        log_files = self._find_log_files("canonical_mapping")
        
        for log_file in log_files:
            try:
                with open(log_file, 'r') as f:
                    for line in f:
                        data = self._parse_canonical_mapping_log(line)
                        if data:
                            # Check canonical mapping
                            result = CanonicalMappingTable.validate_semantic_combination(
                                data["thesis_side"],
                                data["contract_type"],
                                data["position_type"],
                                data["order_action"],
                                data["is_entry"],
                            )
                            
                            severity = self._determine_severity(
                                result.is_valid,
                                CanonicalMappingViolation(result.violation_type.value) if result.violation_type else None,
                            )
                            
                            self.results.append(InvariantResult(
                                invariant_name="Canonical Mapping",
                                severity=severity,
                                is_valid=result.is_valid,
                                violation_type=result.violation_type.value if result.violation_type else None,
                                message=result.message,
                                context=result.context,
                                timestamp=datetime.now(),
                            ))
            
            except Exception as e:
                print(f"Error processing {log_file}: {e}")
    
    def _run_reconciliation_invariants(self):
        """Run reconciliation invariants."""
        print("Running reconciliation invariants...")
        
        checker = ReconciliationInvariantChecker()
        
        log_files = self._find_log_files("reconciliation")
        
        for log_file in log_files:
            try:
                with open(log_file, 'r') as f:
                    for line in f:
                        data = self._parse_reconciliation_log(line)
                        if data:
                            # Create episode
                            episode = Episode(
                                episode_id=data["episode_id"],
                                signals=data["signals"],
                                selected_contract=data["selected_contract"],
                                risk_decision=data["risk_decision"],
                                orders=data["orders"],
                                fills=data["fills"],
                                realized_pnl_usd=data["realized_pnl_usd"],
                                edge_attribution=data["edge_attribution"],
                            )
                            
                            # Check episode conservation
                            result = checker.check_episode_conservation(
                                episode,
                                data["net_position_size"],
                            )
                            
                            severity = self._determine_severity(
                                result.is_valid,
                                ReconciliationViolation(result.violation_type.value) if result.violation_type else None,
                            )
                            
                            self.results.append(InvariantResult(
                                invariant_name="Reconciliation: Episode Conservation",
                                severity=severity,
                                is_valid=result.is_valid,
                                violation_type=result.violation_type.value if result.violation_type else None,
                                message=result.message,
                                context=result.context,
                                timestamp=datetime.now(),
                            ))
            
            except Exception as e:
                print(f"Error processing {log_file}: {e}")
    
    def _run_config_invariants(self):
        """Run configuration invariants."""
        print("Running configuration invariants...")
        
        checker = ConfigInvariantChecker()
        
        # Load production config
        config_file = self.log_dir / "production_config.json"
        if config_file.exists():
            with open(config_file, 'r') as f:
                production_config = json.load(f)
        else:
            production_config = {}
        
        # Check profile alignment
        result = checker.check_profile_alignment(production_config)
        
        severity = self._determine_severity(
            result.is_valid,
            ConfigViolation(result.violation_type.value) if result.violation_type else None,
        )
        
        self.results.append(InvariantResult(
            invariant_name="Config: Profile Alignment",
            severity=severity,
            is_valid=result.is_valid,
            violation_type=result.violation_type.value if result.violation_type else None,
            message=result.message,
            context=result.context,
            timestamp=datetime.now(),
        ))
    
    def _find_log_files(self, pattern: str) -> List[Path]:
        """Find log files matching pattern."""
        return list(self.log_dir.glob(f"*{pattern}*.log"))
    
    def _parse_edge_probability_log(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse edge-probability data from log line."""
        # Example: "EDGE-PROBABILITY: p_model=0.70 edge=0.15 chosen_side=yes"
        match = re.search(r"p_model=([\d.]+)\s+edge=([\d.-]+)\s+chosen_side=(\w+)", line)
        if match:
            return {
                "p_model": float(match.group(1)),
                "edge": float(match.group(2)),
                "chosen_side": match.group(3),
            }
        return None
    
    def _parse_regime_gating_log(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse regime gating data from log line."""
        # Example: "REGIME-GATING: volatility=0.02 flag=normal position_size=1 disabled=False trade=True"
        match = re.search(
            r"volatility=([\d.]+)\s+flag=(\w+)\s+position_size=(\d+)\s+disabled=(\w+)\s+trade=(\w+)",
            line
        )
        if match:
            return {
                "volatility": float(match.group(1)),
                "volatility_flag": match.group(2),
                "position_size": int(match.group(3)),
                "strategy_disabled": match.group(4) == "True",
                "trade_emitted": match.group(5) == "True",
            }
        return None
    
    def _parse_spot_strike_log(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse spot-strike data from log line."""
        # Example: "SPOT-STRIKE: spot=65000.0 strike=65000.0 trade=True"
        match = re.search(r"spot=([\d.]+)\s+strike=([\d.]+)\s+trade=(\w+)", line)
        if match:
            return {
                "spot_price": float(match.group(1)),
                "strike_price": float(match.group(2)),
                "trade_emitted": match.group(3) == "True",
            }
        return None
    
    def _parse_canonical_mapping_log(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse canonical mapping data from log line."""
        # Example: "CANONICAL-MAPPING: thesis=up contract=yes position=long_yes action=buy_yes entry=True"
        match = re.search(
            r"thesis=(\w+)\s+contract=(\w+)\s+position=(\w+)\s+action=(\w+)\s+entry=(\w+)",
            line
        )
        if match:
            return {
                "thesis_side": match.group(1),
                "contract_type": match.group(2),
                "position_type": match.group(3),
                "order_action": match.group(4),
                "is_entry": match.group(5) == "True",
            }
        return None
    
    def _parse_reconciliation_log(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse reconciliation data from log line."""
        # This is a simplified parser - in production, you'd parse structured logs
        # Example: "RECONCILIATION: episode_id=xxx net_position=1 pnl=0.10"
        match = re.search(r"episode_id=(\w+)\s+net_position=(\d+)\s+pnl=([\d.-]+)", line)
        if match:
            return {
                "episode_id": match.group(1),
                "net_position_size": int(match.group(2)),
                "realized_pnl_usd": float(match.group(3)),
                "signals": {},
                "selected_contract": {},
                "risk_decision": {},
                "orders": [],
                "fills": [],
                "edge_attribution": {},
            }
        return None
    
    def _determine_severity(
        self,
        is_valid: bool,
        violation_type: Optional[Any],
    ) -> InvariantSeverity:
        """Determine severity based on violation type."""
        if is_valid:
            return InvariantSeverity.LOW
        
        # Map violation types to severity
        critical_violations = [
            EdgeProbabilityViolation.EDGE_SIGN_MISMATCH,
            RegimeGatingViolation.VOLATILITY_HALT_TRADE,
            ReconciliationViolation.POSITION_SIZE_MISMATCH,
            ReconciliationViolation.NEGATIVE_BALANCE,
        ]
        
        high_violations = [
            EdgeProbabilityViolation.CONFIDENCE_NOT_MONOTONIC,
            RegimeGatingViolation.VOLUME_ILLIQUID_TRADE,
            CanonicalMappingViolation.ILLEGAL_SEMANTIC_COMBINATION,
            ReconciliationViolation.PNL_CALCULATION_MISMATCH,
        ]
        
        if violation_type in critical_violations:
            return InvariantSeverity.CRITICAL
        elif violation_type in high_violations:
            return InvariantSeverity.HIGH
        else:
            return InvariantSeverity.MEDIUM
    
    def generate_report(self, output_file: Optional[str] = None) -> str:
        """Generate markdown report of invariant results."""
        report = "# Production Invariants Report\n\n"
        report += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        report += f"Log Directory: {self.log_dir}\n"
        report += f"Total Checks: {len(self.results)}\n\n"
        
        # Summary statistics
        total = len(self.results)
        passed = sum(1 for r in self.results if r.is_valid)
        failed = total - passed
        
        report += "## Summary\n\n"
        report += f"| Metric | Count |\n"
        report += f"|--------|-------|\n"
        report += f"| Total Checks | {total} |\n"
        report += f"| Passed | {passed} |\n"
        report += f"| Failed | {failed} |\n\n"
        
        # Severity breakdown
        report += "## Severity Breakdown\n\n"
        report += f"| Severity | Count |\n"
        report += f"|----------|-------|\n"
        for severity in InvariantSeverity:
            count = sum(1 for r in self.results if r.severity == severity)
            report += f"| {severity.value} | {count} |\n"
        report += "\n"
        
        # Detailed results
        report += "## Detailed Results\n\n"
        
        # Group by invariant name
        by_invariant: Dict[str, List[InvariantResult]] = {}
        for result in self.results:
            if result.invariant_name not in by_invariant:
                by_invariant[result.invariant_name] = []
            by_invariant[result.invariant_name].append(result)
        
        for invariant_name, results in by_invariant.items():
            report += f"### {invariant_name}\n\n"
            for result in results:
                report += result.to_markdown()
        
        # Critical failures
        critical_failures = [r for r in self.results if r.severity == InvariantSeverity.CRITICAL and not r.is_valid]
        if critical_failures:
            report += "## Critical Failures (Immediate Action Required)\n\n"
            for result in critical_failures:
                report += result.to_markdown()
        
        if output_file:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"Report written to {output_file}")
        
        return report


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Production invariants suite for daily log reconciliation")
    parser.add_argument(
        "--log-dir",
        "-l",
        required=True,
        help="Directory containing production logs"
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output file for report (default: stdout)"
    )
    
    args = parser.parse_args()
    
    suite = ProductionInvariantsSuite(args.log_dir)
    suite.run_all_invariants()
    report = suite.generate_report(args.output)
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    total = len(suite.results)
    passed = sum(1 for r in suite.results if r.is_valid)
    failed = total - passed
    print(f"Total checks: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    
    if failed > 0:
        print(f"\n⚠️  {failed} invariant violations detected. Review the report for details.")
        sys.exit(1)
    else:
        print(f"\n✅ All invariants passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
