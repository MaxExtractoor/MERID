"""
Spread Cap Calibration Engine

Implements data-driven calibration of spread caps for 15-minute Kalshi markets.
Uses historical spread distributions, reject rate analysis, and time-bucket
behavior to set realistic caps that preserve positive-edge opportunities while
rejecting garbage books.
"""

import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple
import json
from pathlib import Path

from merid.event_venues.kalshi.spread_distribution_replay import (
    SpreadMeasurement,
    DistributionStats,
    RejectRateAnalysis,
    AssetAnalysis,
    TimeBucket
)

logger = logging.getLogger(__name__)


class VolatilityRegime(Enum):
    """Volatility regimes for spread behavior"""
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


@dataclass
class CalibrationTarget:
    """Calibration targets for a single asset"""
    asset: str
    target_reject_rate: float  # Target reject rate (0-1)
    min_maker_preservation: float  # Minimum maker opportunity preservation (0-1)
    min_taker_preservation: float  # Minimum taker opportunity preservation (0-1)
    max_time_bucket_variance: float  # Max variance in reject rate across buckets
    min_volatility_robustness: float  # Min score for volatility handling (0-1)
    
    def to_dict(self) -> dict:
        return {
            'asset': self.asset,
            'target_reject_rate': self.target_reject_rate,
            'min_maker_preservation': self.min_maker_preservation,
            'min_taker_preservation': self.min_taker_preservation,
            'max_time_bucket_variance': self.max_time_bucket_variance,
            'min_volatility_robustness': self.min_volatility_robustness,
        }


@dataclass
class TimeBucketCap:
    """Cap for a specific time bucket"""
    bucket: TimeBucket
    base_cap_cents: float
    adjusted_cap_cents: float
    multiplier: float
    expected_reject_rate: float
    expected_false_reject_rate: float
    
    def to_dict(self) -> dict:
        return {
            'bucket': self.bucket.value,
            'base_cap_cents': self.base_cap_cents,
            'adjusted_cap_cents': self.adjusted_cap_cents,
            'multiplier': self.multiplier,
            'expected_reject_rate': self.expected_reject_rate,
            'expected_false_reject_rate': self.expected_false_reject_rate,
        }


@dataclass
class CalibrationResult:
    """Complete calibration result for an asset"""
    asset: str
    base_cap_cents: float
    maker_cap_cents: float
    taker_cap_cents: float
    time_bucket_caps: Dict[TimeBucket, TimeBucketCap]
    expected_reject_rate: float
    expected_false_reject_rate: float
    maker_preservation_rate: float
    taker_preservation_rate: float
    time_bucket_stability_score: float
    volatility_robustness_score: float
    calibration_confidence: str
    calibration_notes: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            'asset': self.asset,
            'base_cap_cents': self.base_cap_cents,
            'maker_cap_cents': self.maker_cap_cents,
            'taker_cap_cents': self.taker_cap_cents,
            'time_bucket_caps': {
                bucket.value: cap.to_dict() 
                for bucket, cap in self.time_bucket_caps.items()
            },
            'expected_reject_rate': self.expected_reject_rate,
            'expected_false_reject_rate': self.expected_false_reject_rate,
            'maker_preservation_rate': self.maker_preservation_rate,
            'taker_preservation_rate': self.taker_preservation_rate,
            'time_bucket_stability_score': self.time_bucket_stability_score,
            'volatility_robustness_score': self.volatility_robustness_score,
            'calibration_confidence': self.calibration_confidence,
            'calibration_notes': self.calibration_notes,
        }


class SpreadCapCalibrator:
    """
    Calibrates spread caps based on historical data and empirical targets.
    
    Implements the decision criteria:
    1. Reject rate target achievement
    2. False reject minimization
    3. Time-bucket stability
    4. Maker preservation
    5. Volatility robustness
    """
    
    # Default calibration targets per asset
    DEFAULT_TARGETS = {
        "BTC": CalibrationTarget(
            asset="BTC",
            target_reject_rate=0.08,  # 8% target
            min_maker_preservation=0.95,  # Preserve 95% of maker opportunities
            min_taker_preservation=0.85,  # Preserve 85% of taker opportunities
            max_time_bucket_variance=0.05,  # Max 5% variance across buckets
            min_volatility_robustness=0.85,  # 85% robustness score
        ),
        "ETH": CalibrationTarget(
            asset="ETH",
            target_reject_rate=0.10,  # 10% target
            min_maker_preservation=0.95,
            min_taker_preservation=0.85,
            max_time_bucket_variance=0.05,
            min_volatility_robustness=0.85,
        ),
        "SOL": CalibrationTarget(
            asset="SOL",
            target_reject_rate=0.15,  # 15% target
            min_maker_preservation=0.94,
            min_taker_preservation=0.80,
            max_time_bucket_variance=0.07,  # More variance allowed
            min_volatility_robustness=0.80,  # Lower robustness requirement
        ),
        "XRP": CalibrationTarget(
            asset="XRP",
            target_reject_rate=0.18,  # 18% target
            min_maker_preservation=0.93,
            min_taker_preservation=0.78,
            max_time_bucket_variance=0.08,
            min_volatility_robustness=0.75,
        ),
        "DOGE": CalibrationTarget(
            asset="DOGE",
            target_reject_rate=0.22,  # 22% target
            min_maker_preservation=0.92,
            min_taker_preservation=0.75,
            max_time_bucket_variance=0.10,  # Highest variance allowed
            min_volatility_robustness=0.70,  # Lowest robustness requirement
        ),
    }
    
    # Time bucket multipliers based on spread behavior
    TIME_BUCKET_MULTIPLIERS = {
        TimeBucket.OPEN_0_3MIN: 1.5,    # Market open: high volatility
        TimeBucket.EARLY_3_6MIN: 1.2,   # Early window: elevated spreads
        TimeBucket.MID_6_10MIN: 1.0,    # Mid window: normal trading
        TimeBucket.LATE_10_13MIN: 1.1,  # Late window: spreads begin to widen
        TimeBucket.EXPIRY_13_15MIN: 1.8, # Near expiry: highest volatility
    }
    
    def __init__(self, targets: Dict[str, CalibrationTarget] = None):
        self.targets = targets or self.DEFAULT_TARGETS
    
    def calibrate_asset(
        self,
        analysis: AssetAnalysis,
        measurements: List[SpreadMeasurement] = None
    ) -> CalibrationResult:
        """
        Calibrate spread caps for a single asset.
        
        Args:
            analysis: Asset analysis from SpreadDistributionAnalyzer
            measurements: Optional raw measurements for detailed analysis
            
        Returns:
            CalibrationResult with recommended caps
        """
        asset = analysis.asset
        target = self.targets.get(asset)
        
        if not target:
            logger.warning(f"[CALIBRATOR] No calibration target for {asset}, using defaults")
            target = CalibrationTarget(
                asset=asset,
                target_reject_rate=0.15,
                min_maker_preservation=0.90,
                min_taker_preservation=0.80,
                max_time_bucket_variance=0.10,
                min_volatility_robustness=0.75,
            )
        
        # Step 1: Select base cap meeting reject rate target
        base_cap = self._select_base_cap(analysis, target)
        
        # Step 2: Calculate time-bucket adjustments
        time_bucket_caps = self._calculate_time_bucket_caps(
            base_cap, analysis, target
        )
        
        # Step 3: Separate maker vs taker caps
        maker_cap, taker_cap = self._calculate_maker_taker_caps(
            base_cap, analysis, target
        )
        
        # Step 4: Calculate expected metrics
        expected_reject_rate = self._estimate_reject_rate(
            base_cap, analysis.cap_analysis
        )
        expected_false_reject_rate = self._estimate_false_reject_rate(
            base_cap, analysis.cap_analysis
        )
        
        # Step 5: Calculate preservation rates
        maker_preservation = self._estimate_maker_preservation(
            maker_cap, analysis
        )
        taker_preservation = self._estimate_taker_preservation(
            taker_cap, analysis
        )
        
        # Step 6: Calculate stability and robustness scores
        stability_score = self._calculate_time_bucket_stability(
            time_bucket_caps, target
        )
        robustness_score = self._calculate_volatility_robustness(
            analysis, target
        )
        
        # Step 7: Determine confidence level
        confidence = self._determine_confidence(
            analysis, stability_score, robustness_score, target
        )
        
        # Step 8: Generate calibration notes
        notes = self._generate_calibration_notes(
            analysis, base_cap, target, stability_score, robustness_score
        )
        
        return CalibrationResult(
            asset=asset,
            base_cap_cents=base_cap,
            maker_cap_cents=maker_cap,
            taker_cap_cents=taker_cap,
            time_bucket_caps=time_bucket_caps,
            expected_reject_rate=expected_reject_rate,
            expected_false_reject_rate=expected_false_reject_rate,
            maker_preservation_rate=maker_preservation,
            taker_preservation_rate=taker_preservation,
            time_bucket_stability_score=stability_score,
            volatility_robustness_score=robustness_score,
            calibration_confidence=confidence,
            calibration_notes=notes,
        )
    
    def _select_base_cap(
        self,
        analysis: AssetAnalysis,
        target: CalibrationTarget
    ) -> float:
        """Select base cap that meets reject rate target"""
        # Filter caps meeting reject rate target
        viable_caps = [
            cap_analysis for cap_analysis in analysis.cap_analysis
            if cap_analysis.reject_rate <= target.target_reject_rate
        ]
        
        if not viable_caps:
            # No caps meet target, use the loosest available
            logger.warning(
                f"[CALIBRATOR] No caps meet target for {analysis.asset}, "
                f"using loosest available"
            )
            return max(c.cap_cents for c in analysis.cap_analysis)
        
        # Among viable, minimize false rejects
        optimal = min(viable_caps, key=lambda c: c.false_reject_rate)
        
        logger.info(
            f"[CALIBRATOR] Selected base cap {optimal.cap_cents}c for {analysis.asset} "
            f"(reject rate: {optimal.reject_rate:.2%}, false reject: {optimal.false_reject_rate:.2%})"
        )
        
        return optimal.cap_cents
    
    def _calculate_time_bucket_caps(
        self,
        base_cap: float,
        analysis: AssetAnalysis,
        target: CalibrationTarget
    ) -> Dict[TimeBucket, TimeBucketCap]:
        """Calculate adjusted caps for each time bucket"""
        time_bucket_caps = {}
        
        for bucket, stats in analysis.time_bucket_stats.items():
            multiplier = self.TIME_BUCKET_MULTIPLIERS.get(bucket, 1.0)
            adjusted_cap = base_cap * multiplier
            
            # Estimate reject rate for this bucket
            bucket_reject_rate = self._estimate_bucket_reject_rate(
                adjusted_cap, stats
            )
            
            # Estimate false reject rate for this bucket
            bucket_false_reject_rate = bucket_reject_rate * 0.2  # 20% of rejects are false
            
            time_bucket_caps[bucket] = TimeBucketCap(
                bucket=bucket,
                base_cap_cents=base_cap,
                adjusted_cap_cents=adjusted_cap,
                multiplier=multiplier,
                expected_reject_rate=bucket_reject_rate,
                expected_false_reject_rate=bucket_false_reject_rate,
            )
        
        return time_bucket_caps
    
    def _calculate_maker_taker_caps(
        self,
        base_cap: float,
        analysis: AssetAnalysis,
        target: CalibrationTarget
    ) -> Tuple[float, float]:
        """Calculate separate maker and taker caps"""
        # Maker cap can be tighter (no spread cost)
        maker_cap = base_cap * 0.85  # 15% tighter for makers
        
        # Taker cap should be base cap (full spread cost)
        taker_cap = base_cap
        
        # Ensure maker cap doesn't go below minimum
        maker_cap = max(maker_cap, 5.0)  # Minimum 5c
        
        logger.info(
            f"[CALIBRATOR] Maker cap: {maker_cap}c, Taker cap: {taker_cap}c "
            f"for {analysis.asset}"
        )
        
        return maker_cap, taker_cap
    
    def _estimate_reject_rate(
        self,
        cap_cents: float,
        cap_analysis: List[RejectRateAnalysis]
    ) -> float:
        """Estimate reject rate for a specific cap"""
        # Find closest cap analysis
        closest = min(
            cap_analysis,
            key=lambda c: abs(c.cap_cents - cap_cents)
        )
        return closest.reject_rate
    
    def _estimate_false_reject_rate(
        self,
        cap_cents: float,
        cap_analysis: List[RejectRateAnalysis]
    ) -> float:
        """Estimate false reject rate for a specific cap"""
        closest = min(
            cap_analysis,
            key=lambda c: abs(c.cap_cents - cap_cents)
        )
        return closest.false_reject_rate
    
    def _estimate_bucket_reject_rate(
        self,
        cap_cents: float,
        stats: DistributionStats
    ) -> float:
        """Estimate reject rate for a time bucket based on distribution"""
        if stats.count == 0:
            return 0.0
        
        # Estimate using percentile approach
        # If cap is at 90th percentile, expect ~10% reject rate
        if cap_cents >= stats.p95_spread:
            return 0.05  # 5% reject rate
        elif cap_cents >= stats.p90_spread:
            return 0.10  # 10% reject rate
        elif cap_cents >= stats.p75_spread:
            return 0.25  # 25% reject rate
        elif cap_cents >= stats.median_spread:
            return 0.50  # 50% reject rate
        else:
            return 0.75  # 75% reject rate
    
    def _estimate_maker_preservation(
        self,
        maker_cap: float,
        analysis: AssetAnalysis
    ) -> float:
        """Estimate maker opportunity preservation rate"""
        # Makers have no spread cost, so preservation is higher
        # Use base cap reject rate and adjust for tighter maker cap
        base_reject = self._estimate_reject_rate(
            analysis.current_cap_cents, analysis.cap_analysis
        )
        
        # Maker cap is 15% tighter, so reject rate is lower
        maker_reject = base_reject * 0.7
        return 1.0 - maker_reject
    
    def _estimate_taker_preservation(
        self,
        taker_cap: float,
        analysis: AssetAnalysis
    ) -> float:
        """Estimate taker opportunity preservation rate"""
        # Takers have full spread cost, so preservation is lower
        base_reject = self._estimate_reject_rate(
            analysis.current_cap_cents, analysis.cap_analysis
        )
        return 1.0 - base_reject
    
    def _calculate_time_bucket_stability(
        self,
        time_bucket_caps: Dict[TimeBucket, TimeBucketCap],
        target: CalibrationTarget
    ) -> float:
        """Calculate stability score across time buckets"""
        reject_rates = [cap.expected_reject_rate for cap in time_bucket_caps.values()]
        
        if not reject_rates:
            return 0.0
        
        # Calculate variance
        mean_rate = statistics.mean(reject_rates)
        variance = statistics.variance(reject_rates) if len(reject_rates) > 1 else 0
        
        # Convert to stability score (lower variance = higher score)
        max_variance = target.max_time_bucket_variance ** 2
        stability = max(0.0, 1.0 - (variance / max_variance))
        
        return stability
    
    def _calculate_volatility_robustness(
        self,
        analysis: AssetAnalysis,
        target: CalibrationTarget
    ) -> float:
        """Calculate volatility robustness score"""
        if not analysis.overall_stats:
            return 0.5
        
        stats = analysis.overall_stats
        
        # Robustness based on spread distribution characteristics
        # Higher std dev relative to mean = lower robustness
        if stats.mean_spread > 0:
            cv = stats.std_spread / stats.mean_spread  # Coefficient of variation
        else:
            cv = 0.0
        
        # Normalize to 0-1 score
        robustness = max(0.0, 1.0 - (cv / 2.0))  # CV of 2.0 = 0 score
        
        return robustness
    
    def _determine_confidence(
        self,
        analysis: AssetAnalysis,
        stability_score: float,
        robustness_score: float,
        target: CalibrationTarget
    ) -> str:
        """Determine calibration confidence level"""
        if not analysis.overall_stats or analysis.overall_stats.count < 100:
            return "LOW"
        
        if (stability_score >= target.min_volatility_robustness and
            robustness_score >= target.min_volatility_robustness):
            return "HIGH"
        elif (stability_score >= target.min_volatility_robustness * 0.8 and
              robustness_score >= target.min_volatility_robustness * 0.8):
            return "MEDIUM"
        else:
            return "LOW"
    
    def _generate_calibration_notes(
        self,
        analysis: AssetAnalysis,
        base_cap: float,
        target: CalibrationTarget,
        stability_score: float,
        robustness_score: float
    ) -> List[str]:
        """Generate calibration notes"""
        notes = []
        
        if analysis.overall_stats:
            stats = analysis.overall_stats
            notes.append(f"Based on {stats.count} samples")
            notes.append(f"90th percentile spread: {stats.p90_spread:.1f}c")
            notes.append(f"Selected cap: {base_cap:.1f}c (vs current {analysis.current_cap_cents}c)")
            
            if base_cap > analysis.current_cap_cents:
                notes.append(f"Cap increased by {((base_cap / analysis.current_cap_cents) - 1) * 100:.1f}%")
            elif base_cap < analysis.current_cap_cents:
                notes.append(f"Cap decreased by {(1 - (base_cap / analysis.current_cap_cents)) * 100:.1f}%")
        
        if stability_score < target.min_volatility_robustness:
            notes.append(f"Time-bucket stability ({stability_score:.2f}) below target")
        
        if robustness_score < target.min_volatility_robustness:
            notes.append(f"Volatility robustness ({robustness_score:.2f}) below target")
        
        return notes
    
    def calibrate_all_assets(
        self,
        analyses: Dict[str, AssetAnalysis]
    ) -> Dict[str, CalibrationResult]:
        """Calibrate all assets"""
        results = {}
        
        for asset, analysis in analyses.items():
            try:
                result = self.calibrate_asset(analysis)
                results[asset] = result
                logger.info(
                    f"[CALIBRATOR] Calibrated {asset}: "
                    f"base_cap={result.base_cap_cents:.1f}c, "
                    f"confidence={result.calibration_confidence}"
                )
            except Exception as e:
                logger.error(f"[CALIBRATOR] Failed to calibrate {asset}: {e}")
        
        return results
    
    def generate_calibration_report(
        self,
        results: Dict[str, CalibrationResult],
        output_file: Path
    ):
        """Generate comprehensive calibration report"""
        with open(output_file, 'w') as f:
            f.write("=" * 80 + "\n")
            f.write("SPREAD CAP CALIBRATION REPORT\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Generated: {datetime.now().isoformat()}\n\n")
            
            # Summary table
            f.write("CALIBRATION SUMMARY\n")
            f.write("=" * 80 + "\n")
            f.write(f"{'Asset':<8} {'Base Cap':<12} {'Maker Cap':<12} {'Taker Cap':<12} ")
            f.write(f"{'Reject Rate':<14} {'False Reject':<14} {'Confidence':<12}\n")
            f.write("-" * 80 + "\n")
            
            for asset, result in results.items():
                f.write(
                    f"{asset:<8} "
                    f"{result.base_cap_cents:<12.1f} "
                    f"{result.maker_cap_cents:<12.1f} "
                    f"{result.taker_cap_cents:<12.1f} "
                    f"{result.expected_reject_rate:<14.2%} "
                    f"{result.expected_false_reject_rate:<14.2%} "
                    f"{result.calibration_confidence:<12}\n"
                )
            
            f.write("\n" + "=" * 80 + "\n\n")
            
            # Detailed per-asset reports
            for asset, result in results.items():
                f.write(f"\n{'=' * 80}\n")
                f.write(f"ASSET: {asset}\n")
                f.write(f"{'=' * 80}\n\n")
                
                f.write(f"Base Cap: {result.base_cap_cents:.1f}c\n")
                f.write(f"Maker Cap: {result.maker_cap_cents:.1f}c\n")
                f.write(f"Taker Cap: {result.taker_cap_cents:.1f}c\n\n")
                
                f.write(f"Expected Reject Rate: {result.expected_reject_rate:.2%}\n")
                f.write(f"Expected False Reject Rate: {result.expected_false_reject_rate:.2%}\n")
                f.write(f"Maker Preservation Rate: {result.maker_preservation_rate:.2%}\n")
                f.write(f"Taker Preservation Rate: {result.taker_preservation_rate:.2%}\n\n")
                
                f.write(f"Time-Bucket Stability Score: {result.time_bucket_stability_score:.2f}\n")
                f.write(f"Volatility Robustness Score: {result.volatility_robustness_score:.2f}\n")
                f.write(f"Calibration Confidence: {result.calibration_confidence}\n\n")
                
                f.write("TIME BUCKET CAPS:\n")
                for bucket, cap in result.time_bucket_caps.items():
                    f.write(
                        f"  {bucket.value:12s}: {cap.adjusted_cap_cents:6.1f}c "
                        f"(x{cap.multiplier:.1f}) | "
                        f"Reject: {cap.expected_reject_rate:.2%}\n"
                    )
                
                f.write("\nCALIBRATION NOTES:\n")
                for note in result.calibration_notes:
                    f.write(f"  - {note}\n")
            
            f.write("\n" + "=" * 80 + "\n")
            f.write("RECOMMENDATIONS\n")
            f.write("=" * 80 + "\n\n")
            
            # Generate recommendations
            self._write_recommendations(f, results)
    
    def _write_recommendations(
        self,
        f,
        results: Dict[str, CalibrationResult]
    ):
        """Write recommendations to report"""
        f.write("1. Deploy calibrated caps with time-bucket adjustments\n")
        f.write("2. Implement separate maker vs taker cap logic\n")
        f.write("3. Monitor actual reject rates vs targets for 7 days\n")
        f.write("4. Schedule weekly recalibration to adapt to market changes\n\n")
        
        f.write("ASSET-SPECIFIC NOTES:\n")
        for asset, result in results.items():
            if result.calibration_confidence == "LOW":
                f.write(f"\n{asset}: LOW confidence - collect more data before deployment\n")
            elif result.time_bucket_stability_score < 0.8:
                f.write(f"\n{asset}: Monitor time-bucket stability closely\n")
            elif result.volatility_robustness_score < 0.8:
                f.write(f"\n{asset}: Monitor volatility regime changes\n")
            else:
                f.write(f"\n{asset}: Ready for deployment\n")
