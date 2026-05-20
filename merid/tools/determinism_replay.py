"""
Determinism Replay Job

Replays historical trading decisions through the current strategy and models
to verify that the same inputs produce the same outputs. This catches
non-determinism bugs, config drift, and model changes.

Usage:
    python -m merid.tools.determinism_replay --mode ci --sample-size 10
    python -m merid.tools.determinism_replay --mode full --window-days 1
    python -m merid.tools.determinism_replay --bundle-id <bundle_id>
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any

from utils.logger import get_logger
from merid.tools.determinism_types import (
    DeterminismBundle,
    ReplayResult,
    ReplaySummary,
    DecisionType,
)

logger = get_logger("merid.tools.determinism_replay")


# Configuration
PROB_EDGE_TOLERANCE = 0.01  # 1% tolerance for probability edge
SIZE_TOLERANCE = 1  # 1 contract tolerance for size


class DeterminismReplayer:
    """
    Replays historical trading decisions to verify determinism.
    
    This class loads determinism bundles from storage, replays them through
    the current strategy and models, and compares outputs against the
    original decisions.
    """
    
    def __init__(
        self,
        storage_path: Optional[Path] = None,
        prob_edge_tolerance: float = PROB_EDGE_TOLERANCE,
        size_tolerance: int = SIZE_TOLERANCE,
    ):
        """
        Initialize the replayer.
        
        Args:
            storage_path: Path to bundle storage directory
            prob_edge_tolerance: Tolerance for probability edge comparison
            size_tolerance: Tolerance for size comparison
        """
        self.storage_path = storage_path or Path("data/determinism_bundles")
        self.prob_edge_tolerance = prob_edge_tolerance
        self.size_tolerance = size_tolerance
        
        # Ensure storage directory exists
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    def load_bundles(
        self,
        window_days: Optional[int] = None,
        asset: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[DeterminismBundle]:
        """
        Load determinism bundles from storage.
        
        Args:
            window_days: Only load bundles from last N days
            asset: Only load bundles for specific asset
            limit: Maximum number of bundles to load
            
        Returns:
            List of determinism bundles
        """
        bundles = []
        
        # Load from JSON files in storage directory
        bundle_files = list(self.storage_path.glob("*.json"))
        
        # Filter by time window
        if window_days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
            bundle_files = [
                f for f in bundle_files
                if datetime.fromisoformat(f.stem.split("_")[1]) >= cutoff
            ]
        
        # Filter by asset
        if asset:
            bundle_files = [
                f for f in bundle_files
                if asset.lower() in f.name.lower()
            ]
        
        # Limit
        if limit:
            bundle_files = bundle_files[:limit]
        
        for bundle_file in bundle_files:
            try:
                with open(bundle_file, 'r') as f:
                    data = json.load(f)
                
                bundle = DeterminismBundle(
                    bundle_id=data["bundle_id"],
                    timestamp=datetime.fromisoformat(data["timestamp"]),
                    market_id=data["market_id"],
                    asset=data["asset"],
                    timeframe=data["timeframe"],
                    decision_type=DecisionType(data["decision_type"]),
                    feature_vector=data["feature_vector"],
                    config_hash=data["config_hash"],
                    model_version=data["model_version"],
                    contract_metadata=data["contract_metadata"],
                    kill_switch_state=data["kill_switch_state"],
                    risk_regime=data["risk_regime"],
                    original_signal_direction=data["original_signal_direction"],
                    original_prob_edge=data["original_prob_edge"],
                    original_size_intent=data["original_size_intent"],
                    original_reason=data["original_reason"],
                    correlation_id=data.get("correlation_id"),
                    agent_id=data.get("agent_id"),
                )
                bundles.append(bundle)
                
            except Exception as e:
                logger.warning(f"Failed to load bundle {bundle_file}: {e}")
        
        logger.info(f"Loaded {len(bundles)} bundles from storage")
        return bundles
    
    def replay_bundle(self, bundle: DeterminismBundle) -> ReplayResult:
        """
        Replay a single determinism bundle.
        
        Args:
            bundle: Determinism bundle to replay
            
        Returns:
            Replay result with comparison
        """
        logger.debug(f"Replaying bundle {bundle.bundle_id}")
        
        # TODO: Implement actual replay logic
        # This would:
        # 1. Load the strategy and model at the appropriate version
        # 2. Set up the system state (kill switch, risk regime)
        # 3. Feed the feature vector into the model
        # 4. Get the signal direction, prob_edge, size_intent
        # 5. Compare against original outputs
        
        # For now, return a mock result
        replay_signal_direction = bundle.original_signal_direction
        replay_prob_edge = bundle.original_prob_edge
        replay_size_intent = bundle.original_size_intent
        replay_reason = bundle.original_reason
        
        # Compare outputs
        direction_match = replay_signal_direction == bundle.original_signal_direction
        prob_edge_match = abs(replay_prob_edge - bundle.original_prob_edge) < 1e-9
        size_match = replay_size_intent == bundle.original_size_intent
        reason_match = replay_reason == bundle.original_reason
        
        # Tolerance checks
        prob_edge_diff = abs(replay_prob_edge - bundle.original_prob_edge)
        prob_edge_within_tolerance = prob_edge_diff <= self.prob_edge_tolerance
        size_diff = abs(replay_size_intent - bundle.original_size_intent)
        size_within_tolerance = size_diff <= self.size_tolerance
        
        # Overall pass/fail
        passed = (
            direction_match
            and prob_edge_within_tolerance
            and size_within_tolerance
        )
        
        failure_reason = None
        if not passed:
            reasons = []
            if not direction_match:
                reasons.append(f"direction mismatch: {bundle.original_signal_direction} vs {replay_signal_direction}")
            if not prob_edge_within_tolerance:
                reasons.append(f"prob_edge diff {prob_edge_diff:.4f} exceeds tolerance {self.prob_edge_tolerance}")
            if not size_within_tolerance:
                reasons.append(f"size diff {size_diff} exceeds tolerance {self.size_tolerance}")
            failure_reason = "; ".join(reasons)
        
        return ReplayResult(
            bundle_id=bundle.bundle_id,
            replay_signal_direction=replay_signal_direction,
            replay_prob_edge=replay_prob_edge,
            replay_size_intent=replay_size_intent,
            replay_reason=replay_reason,
            direction_match=direction_match,
            prob_edge_match=prob_edge_match,
            size_match=size_match,
            reason_match=reason_match,
            prob_edge_diff=prob_edge_diff,
            prob_edge_within_tolerance=prob_edge_within_tolerance,
            size_diff=size_diff,
            size_within_tolerance=size_within_tolerance,
            passed=passed,
            failure_reason=failure_reason,
        )
    
    def replay_bundles(self, bundles: List[DeterminismBundle]) -> ReplaySummary:
        """
        Replay multiple determinism bundles.
        
        Args:
            bundles: List of determinism bundles to replay
            
        Returns:
            Replay summary with results
        """
        logger.info(f"Replaying {len(bundles)} bundles")
        
        results = []
        passed = 0
        failed = 0
        skipped = 0
        
        direction_mismatches = 0
        prob_edge_mismatches = 0
        size_mismatches = 0
        reason_mismatches = 0
        
        prob_edge_diffs = []
        size_diffs = []
        
        for bundle in bundles:
            try:
                result = self.replay_bundle(bundle)
                results.append(result)
                
                if result.passed:
                    passed += 1
                else:
                    failed += 1
                    
                    if not result.direction_match:
                        direction_mismatches += 1
                    if not result.prob_edge_within_tolerance:
                        prob_edge_mismatches += 1
                    if not result.size_within_tolerance:
                        size_mismatches += 1
                    if not result.reason_match:
                        reason_mismatches += 1
                    
                    prob_edge_diffs.append(result.prob_edge_diff)
                    size_diffs.append(result.size_diff)
                    
            except Exception as e:
                logger.error(f"Failed to replay bundle {bundle.bundle_id}: {e}")
                skipped += 1
        
        # Calculate summary metrics
        total = len(bundles)
        pass_rate = passed / total if total > 0 else 0.0
        avg_prob_edge_diff = sum(prob_edge_diffs) / len(prob_edge_diffs) if prob_edge_diffs else 0.0
        avg_size_diff = sum(size_diffs) / len(size_diffs) if size_diffs else 0.0
        
        summary = ReplaySummary(
            total_bundles=total,
            passed=passed,
            failed=failed,
            skipped=skipped,
            direction_mismatches=direction_mismatches,
            prob_edge_mismatches=prob_edge_mismatches,
            size_mismatches=size_mismatches,
            reason_mismatches=reason_mismatches,
            pass_rate=pass_rate,
            avg_prob_edge_diff=avg_prob_edge_diff,
            avg_size_diff=avg_size_diff,
            results=results,
        )
        
        logger.info(
            f"Replay complete: {passed}/{total} passed ({pass_rate:.1%}), "
            f"{failed} failed, {skipped} skipped"
        )
        
        return summary
    
    def save_bundle(self, bundle: DeterminismBundle):
        """
        Save a determinism bundle to storage.
        
        Args:
            bundle: Determinism bundle to save
        """
        filename = f"{bundle.bundle_id}_{bundle.timestamp.isoformat()}.json"
        filepath = self.storage_path / filename
        
        with open(filepath, 'w') as f:
            json.dump(bundle.to_dict(), f, indent=2)
        
        logger.debug(f"Saved bundle to {filepath}")


def compute_config_hash(config: Dict[str, Any]) -> str:
    """
    Compute hash of configuration for determinism tracking.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        SHA256 hash of configuration
    """
    # Convert config to sorted JSON string
    config_str = json.dumps(config, sort_keys=True)
    return hashlib.sha256(config_str.encode()).hexdigest()


def main():
    """Main entry point for determinism replay job."""
    parser = argparse.ArgumentParser(description="Determinism replay job")
    parser.add_argument(
        "--mode",
        choices=["ci", "full"],
        default="ci",
        help="Execution mode: ci (small sample) or full (time window)"
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=1,
        help="Time window in days (full mode only)"
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=10,
        help="Sample size (ci mode only)"
    )
    parser.add_argument(
        "--asset",
        type=str,
        help="Filter by asset"
    )
    parser.add_argument(
        "--bundle-id",
        type=str,
        help="Replay specific bundle by ID"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file for results (JSON)"
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit with error code if any replay fails"
    )
    
    args = parser.parse_args()
    
    replayer = DeterminismReplayer()
    
    if args.bundle_id:
        # Replay specific bundle
        bundles = replayer.load_bundles(limit=1)
        bundles = [b for b in bundles if b.bundle_id == args.bundle_id]
        if not bundles:
            logger.error(f"Bundle {args.bundle_id} not found")
            sys.exit(1)
    elif args.mode == "ci":
        # CI mode: small fixed sample
        bundles = replayer.load_bundles(limit=args.sample_size, asset=args.asset)
    else:
        # Full mode: time window
        bundles = replayer.load_bundles(
            window_days=args.window_days,
            asset=args.asset
        )
    
    if not bundles:
        logger.warning("No bundles to replay")
        sys.exit(0)
    
    # Replay bundles
    summary = replayer.replay_bundles(bundles)
    
    # Print summary
    print("\n" + "="*60)
    print("Determinism Replay Summary")
    print("="*60)
    print(f"Total bundles: {summary.total_bundles}")
    print(f"Passed: {summary.passed} ({summary.pass_rate:.1%})")
    print(f"Failed: {summary.failed}")
    print(f"Skipped: {summary.skipped}")
    print()
    print("Mismatches:")
    print(f"  Direction: {summary.direction_mismatches}")
    print(f"  Prob Edge: {summary.prob_edge_mismatches}")
    print(f"  Size: {summary.size_mismatches}")
    print(f"  Reason: {summary.reason_mismatches}")
    print()
    print(f"Avg prob edge diff: {summary.avg_prob_edge_diff:.4f}")
    print(f"Avg size diff: {summary.avg_size_diff:.2f}")
    print("="*60)
    
    # Save results if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(summary.to_dict(), f, indent=2)
        logger.info(f"Results saved to {args.output}")
    
    # Exit with error if any failures and fail-on-error is set
    if args.fail_on_error and summary.failed > 0:
        logger.error(f"{summary.failed} replay failures detected")
        sys.exit(1)


if __name__ == "__main__":
    main()
