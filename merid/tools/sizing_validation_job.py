"""
Sizing Validation Job

Validates that sizing decisions are consistent over time by comparing
stored intended sizes against recomputed values and actual fills.

Usage:
    python -m merid.tools.sizing_validation_job --window-hours 24
    python -m merid.tools.sizing_validation_job --order-id <order_id>
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any

from utils.logger import get_logger
from merid.tools.sizing_types import (
    SizingDecision,
    SizingValidationResult,
    SizingValidationSummary,
    AppliedConstraint,
    ConstraintType,
)

logger = get_logger("merid.tools.sizing_validation_job")


# Configuration
SIZE_TOLERANCE = 1  # 1 contract tolerance for size
NOTIONAL_TOLERANCE = 0.01  # 1% tolerance for notional


class SizingValidator:
    """
    Validates sizing decisions for consistency.
    
    This class loads sizing decisions from storage, recomputes them
    from raw inputs, and compares against stored values and actual fills.
    """
    
    def __init__(
        self,
        storage_path: Optional[Path] = None,
        size_tolerance: int = SIZE_TOLERANCE,
        notional_tolerance: float = NOTIONAL_TOLERANCE,
    ):
        """
        Initialize the validator.
        
        Args:
            storage_path: Path to sizing decision storage directory
            size_tolerance: Tolerance for size comparison (contracts)
            notional_tolerance: Tolerance for notional comparison (percentage)
        """
        self.storage_path = storage_path or Path("data/sizing_decisions")
        self.size_tolerance = size_tolerance
        self.notional_tolerance = notional_tolerance
        
        # Ensure storage directory exists
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    def load_decisions(
        self,
        window_hours: Optional[int] = None,
        asset: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[SizingDecision]:
        """
        Load sizing decisions from storage.
        
        Args:
            window_hours: Only load decisions from last N hours
            asset: Only load decisions for specific asset
            limit: Maximum number of decisions to load
            
        Returns:
            List of sizing decisions
        """
        decisions = []
        
        # Load from JSON files in storage directory
        decision_files = list(self.storage_path.glob("*.json"))
        
        # Filter by time window
        if window_hours:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
            decision_files = [
                f for f in decision_files
                if datetime.fromisoformat(f.stem.split("_")[1]) >= cutoff
            ]
        
        # Filter by asset
        if asset:
            decision_files = [
                f for f in decision_files
                if asset.lower() in f.name.lower()
            ]
        
        # Limit
        if limit:
            decision_files = decision_files[:limit]
        
        for decision_file in decision_files:
            try:
                with open(decision_file, 'r') as f:
                    data = json.load(f)
                
                constraints = []
                for c_data in data.get("constraints_applied", []):
                    constraints.append(AppliedConstraint(
                        constraint_type=ConstraintType(c_data["constraint_type"]),
                        original_size=c_data["original_size"],
                        adjusted_size=c_data["adjusted_size"],
                        reason=c_data["reason"],
                        metadata=c_data.get("metadata", {}),
                    ))
                
                decision = SizingDecision(
                    decision_id=data["decision_id"],
                    timestamp=datetime.fromisoformat(data["timestamp"]),
                    market_id=data["market_id"],
                    asset=data["asset"],
                    order_id=data.get("order_id"),
                    base_kelly_size=data["base_kelly_size"],
                    base_size=data["base_size"],
                    base_notional_usd=data["base_notional_usd"],
                    intended_size=data["intended_size"],
                    intended_notional_usd=data["intended_notional_usd"],
                    constraints_applied=constraints,
                    bankroll_usd=data["bankroll_usd"],
                    max_position_usd=data["max_position_usd"],
                    risk_regime=data["risk_regime"],
                    sentiment_regime=data["sentiment_regime"],
                    volatility_regime=data["volatility_regime"],
                    sizing_version_hash=data["sizing_version_hash"],
                    config_hash=data["config_hash"],
                    correlation_id=data.get("correlation_id"),
                    agent_id=data.get("agent_id"),
                    strategy=data.get("strategy", "unknown"),
                )
                decisions.append(decision)
                
            except Exception as e:
                logger.warning(f"Failed to load decision {decision_file}: {e}")
        
        logger.info(f"Loaded {len(decisions)} decisions from storage")
        return decisions
    
    def recompute_decision(self, decision: SizingDecision) -> SizingDecision:
        """
        Recompute a sizing decision from raw inputs.
        
        Args:
            decision: Original sizing decision
            
        Returns:
            Recomputed sizing decision
        """
        logger.debug(f"Recomputing decision {decision.decision_id}")

        # NOTE: Recomputation logic not yet implemented
        # This would require:
        # 1. Loading the sizing logic at the appropriate version
        # 2. Feeding the base inputs (bankroll, Kelly fraction, etc.)
        # 3. Applying the same constraints
        # 4. Returning the recomputed decision
        # For now, return the original decision as a placeholder
        return decision
    
    def validate_decision(
        self,
        decision: SizingDecision,
        actual_fill_size: Optional[int] = None,
        actual_fill_notional: Optional[float] = None,
    ) -> SizingValidationResult:
        """
        Validate a single sizing decision.
        
        Args:
            decision: Sizing decision to validate
            actual_fill_size: Actual fill size from venue
            actual_fill_notional: Actual fill notional from venue
            
        Returns:
            Validation result
        """
        logger.debug(f"Validating decision {decision.decision_id}")
        
        # Recompute decision
        recomputed = self.recompute_decision(decision)
        
        # Compare stored vs recomputed
        intended_size_match = decision.intended_size == recomputed.intended_size
        intended_notional_match = abs(decision.intended_notional_usd - recomputed.intended_notional_usd) < 1e-9
        
        intended_size_diff = abs(decision.intended_size - recomputed.intended_size)
        intended_notional_diff = abs(decision.intended_notional_usd - recomputed.intended_notional_usd)
        
        # Compare intended vs actual (if fill data available)
        actual_size_match = True
        actual_notional_match = True
        actual_size_diff = None
        actual_notional_diff = None
        
        if actual_fill_size is not None:
            actual_size_match = decision.intended_size == actual_fill_size
            actual_size_diff = abs(decision.intended_size - actual_fill_size)
        
        if actual_fill_notional is not None:
            actual_notional_match = abs(decision.intended_notional_usd - actual_fill_notional) < 1e-9
            actual_notional_diff = abs(decision.intended_notional_usd - actual_fill_notional)
        
        # Tolerance checks
        within_tolerance = (
            intended_size_diff <= self.size_tolerance
            and (intended_notional_diff / decision.intended_notional_usd if decision.intended_notional_usd > 0 else 0) <= self.notional_tolerance
        )
        
        tolerance_reason = None
        if not within_tolerance:
            reasons = []
            if intended_size_diff > self.size_tolerance:
                reasons.append(f"size diff {intended_size_diff} exceeds tolerance {self.size_tolerance}")
            if (intended_notional_diff / decision.intended_notional_usd if decision.intended_notional_usd > 0 else 0) > self.notional_tolerance:
                reasons.append(f"notional diff {intended_notional_diff:.2f} exceeds tolerance {self.notional_tolerance}")
            tolerance_reason = "; ".join(reasons)
        
        # Overall pass/fail
        passed = (
            intended_size_match
            and intended_notional_match
            and within_tolerance
        )
        
        failure_reason = None
        if not passed:
            reasons = []
            if not intended_size_match:
                reasons.append(f"intended size mismatch: {decision.intended_size} vs {recomputed.intended_size}")
            if not intended_notional_match:
                reasons.append(f"intended notional mismatch: {decision.intended_notional_usd:.2f} vs {recomputed.intended_notional_usd:.2f}")
            if not within_tolerance and tolerance_reason:
                reasons.append(tolerance_reason)
            failure_reason = "; ".join(reasons)
        
        return SizingValidationResult(
            decision_id=decision.decision_id,
            stored_intended_size=decision.intended_size,
            recomputed_intended_size=recomputed.intended_size,
            stored_notional=decision.intended_notional_usd,
            recomputed_notional=recomputed.intended_notional_usd,
            actual_fill_size=actual_fill_size,
            actual_fill_notional=actual_fill_notional,
            intended_size_match=intended_size_match,
            intended_notional_match=intended_notional_match,
            actual_size_match=actual_size_match,
            actual_notional_match=actual_notional_match,
            intended_size_diff=intended_size_diff,
            intended_notional_diff=intended_notional_diff,
            actual_size_diff=actual_size_diff,
            actual_notional_diff=actual_notional_diff,
            within_tolerance=within_tolerance,
            tolerance_reason=tolerance_reason,
            passed=passed,
            failure_reason=failure_reason,
        )
    
    def validate_decisions(self, decisions: List[SizingDecision]) -> SizingValidationSummary:
        """
        Validate multiple sizing decisions.
        
        Args:
            decisions: List of sizing decisions to validate
            
        Returns:
            Validation summary
        """
        logger.info(f"Validating {len(decisions)} decisions")
        
        results = []
        passed = 0
        failed = 0
        skipped = 0
        
        intended_size_mismatches = 0
        intended_notional_mismatches = 0
        actual_size_mismatches = 0
        actual_notional_mismatches = 0
        
        intended_size_diffs = []
        intended_notional_diffs = []
        
        for decision in decisions:
            try:
                result = self.validate_decision(decision)
                results.append(result)
                
                if result.passed:
                    passed += 1
                else:
                    failed += 1
                    
                    if not result.intended_size_match:
                        intended_size_mismatches += 1
                    if not result.intended_notional_match:
                        intended_notional_mismatches += 1
                    if not result.actual_size_match:
                        actual_size_mismatches += 1
                    if not result.actual_notional_match:
                        actual_notional_mismatches += 1
                    
                    intended_size_diffs.append(result.intended_size_diff)
                    intended_notional_diffs.append(result.intended_notional_diff)
                    
            except Exception as e:
                logger.error(f"Failed to validate decision {decision.decision_id}: {e}")
                skipped += 1
        
        # Calculate summary metrics
        total = len(decisions)
        pass_rate = passed / total if total > 0 else 0.0
        avg_intended_size_diff = sum(intended_size_diffs) / len(intended_size_diffs) if intended_size_diffs else 0.0
        avg_intended_notional_diff = sum(intended_notional_diffs) / len(intended_notional_diffs) if intended_notional_diffs else 0.0
        
        summary = SizingValidationSummary(
            total_decisions=total,
            passed=passed,
            failed=failed,
            skipped=skipped,
            intended_size_mismatches=intended_size_mismatches,
            intended_notional_mismatches=intended_notional_mismatches,
            actual_size_mismatches=actual_size_mismatches,
            actual_notional_mismatches=actual_notional_mismatches,
            pass_rate=pass_rate,
            avg_intended_size_diff=avg_intended_size_diff,
            avg_intended_notional_diff=avg_intended_notional_diff,
            results=results,
        )
        
        logger.info(
            f"Validation complete: {passed}/{total} passed ({pass_rate:.1%}), "
            f"{failed} failed, {skipped} skipped"
        )
        
        return summary
    
    def save_decision(self, decision: SizingDecision):
        """
        Save a sizing decision to storage.
        
        Args:
            decision: Sizing decision to save
        """
        filename = f"{decision.decision_id}_{decision.timestamp.isoformat()}.json"
        filepath = self.storage_path / filename
        
        with open(filepath, 'w') as f:
            json.dump(decision.to_dict(), f, indent=2)
        
        logger.debug(f"Saved decision to {filepath}")


def compute_sizing_version_hash() -> str:
    """
    Compute hash of sizing logic version for tracking.
    
    Returns:
        SHA256 hash of sizing logic
    """
    # TODO: Implement actual hash computation
    # This would hash the relevant sizing logic files
    return "mock_sizing_version_hash"


def main():
    """Main entry point for sizing validation job."""
    parser = argparse.ArgumentParser(description="Sizing validation job")
    parser.add_argument(
        "--window-hours",
        type=int,
        default=24,
        help="Time window in hours"
    )
    parser.add_argument(
        "--asset",
        type=str,
        help="Filter by asset"
    )
    parser.add_argument(
        "--decision-id",
        type=str,
        help="Validate specific decision by ID"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file for results (JSON)"
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit with error code if any validation fails"
    )
    
    args = parser.parse_args()
    
    validator = SizingValidator()
    
    if args.decision_id:
        # Validate specific decision
        decisions = validator.load_decisions(limit=1)
        decisions = [d for d in decisions if d.decision_id == args.decision_id]
        if not decisions:
            logger.error(f"Decision {args.decision_id} not found")
            sys.exit(1)
    else:
        # Validate time window
        decisions = validator.load_decisions(
            window_hours=args.window_hours,
            asset=args.asset
        )
    
    if not decisions:
        logger.warning("No decisions to validate")
        sys.exit(0)
    
    # Validate decisions
    summary = validator.validate_decisions(decisions)
    
    # Print summary
    print("\n" + "="*60)
    print("Sizing Validation Summary")
    print("="*60)
    print(f"Total decisions: {summary.total_decisions}")
    print(f"Passed: {summary.passed} ({summary.pass_rate:.1%})")
    print(f"Failed: {summary.failed}")
    print(f"Skipped: {summary.skipped}")
    print()
    print("Mismatches:")
    print(f"  Intended size: {summary.intended_size_mismatches}")
    print(f"  Intended notional: {summary.intended_notional_mismatches}")
    print(f"  Actual size: {summary.actual_size_mismatches}")
    print(f"  Actual notional: {summary.actual_notional_mismatches}")
    print()
    print(f"Avg intended size diff: {summary.avg_intended_size_diff:.2f}")
    print(f"Avg intended notional diff: ${summary.avg_intended_notional_diff:.2f}")
    print("="*60)
    
    # Save results if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(summary.to_dict(), f, indent=2)
        logger.info(f"Results saved to {args.output}")
    
    # Exit with error if any failures and fail-on-error is set
    if args.fail_on_error and summary.failed > 0:
        logger.error(f"{summary.failed} validation failures detected")
        sys.exit(1)


if __name__ == "__main__":
    main()
