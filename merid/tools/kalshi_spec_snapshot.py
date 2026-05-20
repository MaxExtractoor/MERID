"""
Kalshi Spec Validation Job

Validates Kalshi API specifications against expected values to detect
breaking changes in contract sizing, fixed-point fields, and other
risk-relevant metadata.

Usage:
    python -m merid.tools.kalshi_spec_snapshot --mode validate
    python -m merid.tools.kalshi_spec_snapshot --mode snapshot --output config/kalshi_expected_spec.yaml
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import yaml

from utils.logger import get_logger

logger = get_logger("merid.tools.kalshi_spec_snapshot")


@dataclass(frozen=True)
class KalshiContractSpec:
    """Kalshi contract specification."""
    # Price fields
    min_price_cents: int
    max_price_cents: int
    tick_size_cents: int
    
    # Size fields
    min_contracts: int
    max_contracts: int
    contract_multiplier: int  # Contracts per unit
    
    # Fixed-point fields
    count_fp_scale: int  # Scale factor for count_fp field
    price_fp_scale: int  # Scale factor for price_fp field
    
    # Risk-relevant metadata
    order_types: List[str] = field(default_factory=list)
    time_in_force: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "min_price_cents": self.min_price_cents,
            "max_price_cents": self.max_price_cents,
            "tick_size_cents": self.tick_size_cents,
            "min_contracts": self.min_contracts,
            "max_contracts": self.max_contracts,
            "contract_multiplier": self.contract_multiplier,
            "count_fp_scale": self.count_fp_scale,
            "price_fp_scale": self.price_fp_scale,
            "order_types": self.order_types,
            "time_in_force": self.time_in_force,
        }


@dataclass
class SpecValidationResult:
    """Result of spec validation."""
    field_name: str
    expected_value: Any
    actual_value: Any
    match: bool
    risk_relevant: bool = True
    failure_reason: Optional[str] = None


@dataclass
class SpecValidationSummary:
    """Summary of spec validation."""
    total_fields: int
    passed: int
    failed: int
    risk_relevant_failures: int
    
    results: List[SpecValidationResult] = field(default_factory=list)
    validation_timestamp: datetime = field(default_factory=lambda: datetime.now())
    
    def passed(self) -> bool:
        """Check if validation passed (no risk-relevant failures)."""
        return self.risk_relevant_failures == 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_fields": self.total_fields,
            "passed": self.passed,
            "failed": self.failed,
            "risk_relevant_failures": self.risk_relevant_failures,
            "validation_timestamp": self.validation_timestamp.isoformat(),
            "results": [
                {
                    "field_name": r.field_name,
                    "expected_value": r.expected_value,
                    "actual_value": r.actual_value,
                    "match": r.match,
                    "risk_relevant": r.risk_relevant,
                    "failure_reason": r.failure_reason,
                }
                for r in self.results
            ],
        }


class KalshiSpecValidator:
    """
    Validates Kalshi API specifications against expected values.
    
    This tool fetches live Kalshi metadata and compares it against
    a stored expected spec to detect breaking changes.
    """
    
    def __init__(self, expected_spec_path: Optional[Path] = None):
        """
        Initialize the validator.
        
        Args:
            expected_spec_path: Path to expected spec YAML file
        """
        self.expected_spec_path = expected_spec_path or Path("config/kalshi_expected_spec.yaml")
    
    def fetch_live_spec(self) -> KalshiContractSpec:
        """
        Fetch live specification from Kalshi API.
        
        Returns:
            Current Kalshi contract spec
        """
        logger.info("Fetching live Kalshi specification")
        
        # TODO: Implement actual Kalshi API call
        # This would:
        # 1. Call Kalshi event/market metadata endpoints
        # 2. Extract contract specs from response
        # 3. Normalize into KalshiContractSpec structure
        
        # For now, return a mock spec
        return KalshiContractSpec(
            min_price_cents=1,
            max_price_cents=99,
            tick_size_cents=1,
            min_contracts=1,
            max_contracts=10000,
            contract_multiplier=1,
            count_fp_scale=100,  # count_fp is cents * 100
            price_fp_scale=100,  # price_fp is cents * 100
            order_types=["limit", "market"],
            time_in_force=["GTC", "IOC", "FOK"],
        )
    
    def load_expected_spec(self) -> Optional[KalshiContractSpec]:
        """
        Load expected specification from YAML file.
        
        Returns:
            Expected Kalshi contract spec, or None if file doesn't exist
        """
        if not self.expected_spec_path.exists():
            logger.warning(f"Expected spec file not found: {self.expected_spec_path}")
            return None
        
        logger.info(f"Loading expected spec from {self.expected_spec_path}")
        
        with open(self.expected_spec_path, 'r') as f:
            data = yaml.safe_load(f)
        
        return KalshiContractSpec(
            min_price_cents=data["min_price_cents"],
            max_price_cents=data["max_price_cents"],
            tick_size_cents=data["tick_size_cents"],
            min_contracts=data["min_contracts"],
            max_contracts=data["max_contracts"],
            contract_multiplier=data["contract_multiplier"],
            count_fp_scale=data["count_fp_scale"],
            price_fp_scale=data["price_fp_scale"],
            order_types=data.get("order_types", []),
            time_in_force=data.get("time_in_force", []),
        )
    
    def save_expected_spec(self, spec: KalshiContractSpec):
        """
        Save expected specification to YAML file.
        
        Args:
            spec: Kalshi contract spec to save
        """
        logger.info(f"Saving expected spec to {self.expected_spec_path}")
        
        # Ensure parent directory exists
        self.expected_spec_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.expected_spec_path, 'w') as f:
            yaml.dump(spec.to_dict(), f, default_flow_style=False, sort_keys=False)
        
        logger.info(f"Saved expected spec to {self.expected_spec_path}")
    
    def validate_spec(
        self,
        expected: KalshiContractSpec,
        actual: KalshiContractSpec,
    ) -> SpecValidationSummary:
        """
        Validate actual spec against expected spec.
        
        Args:
            expected: Expected specification
            actual: Actual (live) specification
            
        Returns:
            Validation summary
        """
        logger.info("Validating Kalshi specification")
        
        results = []
        passed = 0
        failed = 0
        risk_relevant_failures = 0
        
        # Define fields to validate
        fields_to_validate = [
            ("min_price_cents", True),
            ("max_price_cents", True),
            ("tick_size_cents", True),
            ("min_contracts", True),
            ("max_contracts", True),
            ("contract_multiplier", True),
            ("count_fp_scale", True),
            ("price_fp_scale", True),
            ("order_types", False),  # Less risk-relevant
            ("time_in_force", False),  # Less risk-relevant
        ]
        
        for field_name, risk_relevant in fields_to_validate:
            expected_value = getattr(expected, field_name)
            actual_value = getattr(actual, field_name)
            
            match = expected_value == actual_value
            
            if match:
                passed += 1
            else:
                failed += 1
                if risk_relevant:
                    risk_relevant_failures += 1
            
            failure_reason = None
            if not match:
                failure_reason = f"Expected {expected_value}, got {actual_value}"
            
            results.append(SpecValidationResult(
                field_name=field_name,
                expected_value=expected_value,
                actual_value=actual_value,
                match=match,
                risk_relevant=risk_relevant,
                failure_reason=failure_reason,
            ))
        
        total = len(fields_to_validate)
        
        summary = SpecValidationSummary(
            total_fields=total,
            passed=passed,
            failed=failed,
            risk_relevant_failures=risk_relevant_failures,
            results=results,
        )
        
        logger.info(
            f"Validation complete: {passed}/{total} passed, "
            f"{failed} failed, {risk_relevant_failures} risk-relevant failures"
        )
        
        return summary
    
    def emit_prometheus_metrics(self, summary: SpecValidationSummary):
        """
        Emit Prometheus metrics for spec validation.
        
        Args:
            summary: Validation summary
        """
        # TODO: Implement Prometheus metrics emission
        # Metrics to emit:
        # - merid_kalshi_spec_validation_status (0=fail, 1=pass)
        # - merid_kalshi_spec_mismatch_total (by field_name)
        logger.info("Would emit Prometheus metrics here")


def main():
    """Main entry point for Kalshi spec validation job."""
    parser = argparse.ArgumentParser(description="Kalshi spec validation job")
    parser.add_argument(
        "--mode",
        choices=["snapshot", "validate"],
        default="validate",
        help="Mode: snapshot (save current spec) or validate (compare against expected)"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file for snapshot (YAML)"
    )
    parser.add_argument(
        "--fail-on-mismatch",
        action="store_true",
        help="Exit with error code if risk-relevant mismatches detected"
    )
    
    args = parser.parse_args()
    
    validator = KalshiSpecValidator()
    
    if args.output:
        validator.expected_spec_path = Path(args.output)
    
    # Fetch live spec
    live_spec = validator.fetch_live_spec()
    
    if args.mode == "snapshot":
        # Save current spec as expected
        validator.save_expected_spec(live_spec)
        logger.info(f"Saved current spec to {validator.expected_spec_path}")
        sys.exit(0)
    
    # Validate mode
    expected_spec = validator.load_expected_spec()
    
    if expected_spec is None:
        logger.error("Expected spec not found. Run with --mode snapshot first.")
        sys.exit(1)
    
    # Validate
    summary = validator.validate_spec(expected_spec, live_spec)
    
    # Print summary
    print("\n" + "="*60)
    print("Kalshi Spec Validation Summary")
    print("="*60)
    print(f"Total fields: {summary.total_fields}")
    print(f"Passed: {summary.passed}")
    print(f"Failed: {summary.failed}")
    print(f"Risk-relevant failures: {summary.risk_relevant_failures}")
    print()
    
    if summary.failed > 0:
        print("Mismatches:")
        for result in summary.results:
            if not result.match:
                risk_marker = " [RISK]" if result.risk_relevant else ""
                print(f"  {result.field_name}{risk_marker}: {result.failure_reason}")
    
    print("="*60)
    
    # Emit metrics
    validator.emit_prometheus_metrics(summary)
    
    # Exit with error if risk-relevant mismatches and fail-on-mismatch is set
    if args.fail_on_mismatch and summary.risk_relevant_failures > 0:
        logger.error(f"{summary.risk_relevant_failures} risk-relevant spec mismatches detected")
        sys.exit(1)


if __name__ == "__main__":
    main()
