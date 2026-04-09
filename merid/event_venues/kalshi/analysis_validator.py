"""AnalysisValidator — Timestamp validation, drift detection, and clock monitoring.

Implements critical fixes:
- A-001 (HIGH): Timestamp validation on sentiment inputs
- A-002 (HIGH): Drift detection on feature distributions
- A-003 (HIGH): Clock skew monitoring

Protects against:
1. Stale sentiment data being treated as current
2. Schema/distribution changes going undetected
3. Time-based logic breaking due to clock drift
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
import statistics

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.analysis_validator")


# ── Timestamp Validation ─────────────────────────────────────────────────────


@dataclass
class TimestampValidationResult:
    """Result of timestamp validation."""
    valid: bool
    age_seconds: Optional[float] = None
    error: Optional[str] = None
    source: Optional[str] = None


class TimestampValidator:
    """Validates timestamps on sentiment and external data inputs.

    Prevents stale data (e.g., 6h old Twitter sentiment) from being
    treated as current market conditions.
    """

    def __init__(
        self,
        *,
        max_age_seconds: float = 3600,  # 1 hour default
        warn_age_seconds: float = 1800,  # 30 min warning threshold
    ):
        """Initialize validator.

        Args:
            max_age_seconds: Maximum acceptable data age (default 1h)
            warn_age_seconds: Age threshold for warnings (default 30min)
        """
        self.max_age_seconds = max_age_seconds
        self.warn_age_seconds = warn_age_seconds

        # Stats
        self.total_checks = 0
        self.total_valid = 0
        self.total_stale = 0
        self.total_invalid = 0

    def validate_timestamp(
        self,
        timestamp: datetime,
        *,
        source: str = "unknown",
        now: Optional[datetime] = None,
    ) -> TimestampValidationResult:
        """Validate that a timestamp is recent enough.

        Args:
            timestamp: Datetime to validate (must be timezone-aware)
            source: Source identifier for logging (e.g., "twitter", "news")
            now: Current time (defaults to datetime.now(timezone.utc))

        Returns:
            TimestampValidationResult with validity and age info
        """
        self.total_checks += 1

        if now is None:
            now = datetime.now(timezone.utc)

        # Ensure timezone-aware
        if timestamp.tzinfo is None:
            error = f"Timestamp from {source} is timezone-naive"
            logger.error(error)
            self.total_invalid += 1
            return TimestampValidationResult(
                valid=False,
                error=error,
                source=source,
            )

        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # Calculate age
        age_seconds = (now - timestamp).total_seconds()

        # Future timestamps are invalid
        if age_seconds < 0:
            error = f"Timestamp from {source} is in the future by {-age_seconds:.0f}s"
            logger.error(error)
            self.total_invalid += 1
            return TimestampValidationResult(
                valid=False,
                age_seconds=age_seconds,
                error=error,
                source=source,
            )

        # Check staleness
        if age_seconds > self.max_age_seconds:
            error = f"Timestamp from {source} is stale: {age_seconds:.0f}s old (max {self.max_age_seconds:.0f}s)"
            logger.warning(error)
            self.total_stale += 1
            return TimestampValidationResult(
                valid=False,
                age_seconds=age_seconds,
                error=error,
                source=source,
            )

        # Warn if approaching limit
        if age_seconds > self.warn_age_seconds:
            logger.debug(
                f"Timestamp from {source} is getting stale: {age_seconds:.0f}s old "
                f"(warn threshold {self.warn_age_seconds:.0f}s)"
            )

        self.total_valid += 1
        return TimestampValidationResult(
            valid=True,
            age_seconds=age_seconds,
            source=source,
        )


# ── Feature Drift Detection ──────────────────────────────────────────────────


@dataclass
class FeatureStats:
    """Statistical profile of a feature."""
    mean: float
    std: float
    min_val: float
    max_val: float
    sample_count: int
    last_update: datetime


@dataclass
class DriftDetectionResult:
    """Result of drift detection check."""
    drifted: bool
    feature_name: str
    current_value: float
    baseline_mean: float
    baseline_std: float
    z_score: float
    drift_magnitude: str  # "none", "minor", "moderate", "severe"


class FeatureDriftDetector:
    """Detects distribution shifts in model features.

    Tracks baseline statistics for each feature and alerts when
    current values deviate significantly (>3σ from baseline).

    Example features:
    - sentiment_score: Twitter/news sentiment
    - orderbook_imbalance: Bid/ask depth ratio
    - volume_spike: Volume vs 24h average
    - spread_bps: Bid-ask spread in basis points
    """

    def __init__(
        self,
        *,
        baseline_window_size: int = 1000,
        z_score_threshold: float = 3.0,
        update_baseline_on_minor_drift: bool = True,
    ):
        """Initialize drift detector.

        Args:
            baseline_window_size: Number of samples for baseline stats
            z_score_threshold: Z-score threshold for drift alert (default 3σ)
            update_baseline_on_minor_drift: Whether to update baseline on minor drifts
        """
        self.baseline_window_size = baseline_window_size
        self.z_score_threshold = z_score_threshold
        self.update_baseline_on_minor_drift = update_baseline_on_minor_drift

        # Feature baselines
        self._baselines: Dict[str, FeatureStats] = {}
        self._feature_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=baseline_window_size))

        # Stats
        self.total_checks = 0
        self.drift_detections = 0

    def update_baseline(self, feature_name: str, value: float) -> None:
        """Add a sample to the baseline for a feature.

        Args:
            feature_name: Name of the feature
            value: Feature value
        """
        history = self._feature_history[feature_name]
        history.append(value)

        if len(history) >= 10:  # Need at least 10 samples for stats
            self._baselines[feature_name] = FeatureStats(
                mean=statistics.mean(history),
                std=statistics.stdev(history) if len(history) > 1 else 0.0,
                min_val=min(history),
                max_val=max(history),
                sample_count=len(history),
                last_update=datetime.now(timezone.utc),
            )

    def check_drift(
        self,
        feature_name: str,
        current_value: float,
        *,
        auto_update: bool = True,
    ) -> DriftDetectionResult:
        """Check if current feature value has drifted from baseline.

        Args:
            feature_name: Name of the feature
            current_value: Current feature value
            auto_update: Whether to update baseline with this value

        Returns:
            DriftDetectionResult with drift status and magnitude
        """
        self.total_checks += 1

        # No baseline yet - initialize
        if feature_name not in self._baselines:
            if auto_update:
                self.update_baseline(feature_name, current_value)
            return DriftDetectionResult(
                drifted=False,
                feature_name=feature_name,
                current_value=current_value,
                baseline_mean=current_value,
                baseline_std=0.0,
                z_score=0.0,
                drift_magnitude="none",
            )

        baseline = self._baselines[feature_name]

        # Calculate z-score
        if baseline.std == 0:
            # Perfect baseline consistency: any deviation is extreme drift
            z_score = 0.0 if current_value == baseline.mean else float("inf")
        else:
            z_score = abs((current_value - baseline.mean) / baseline.std)

        # Classify drift magnitude
        if z_score < 2.0:
            magnitude = "none"
            drifted = False
        elif z_score < 3.0:
            magnitude = "minor"
            drifted = False
            if self.update_baseline_on_minor_drift and auto_update:
                self.update_baseline(feature_name, current_value)
        elif z_score < 5.0:
            magnitude = "moderate"
            drifted = True
        else:
            magnitude = "severe"
            drifted = True

        if drifted:
            self.drift_detections += 1
            logger.warning(
                f"Feature drift detected: {feature_name}={current_value:.4f} "
                f"(baseline μ={baseline.mean:.4f}, σ={baseline.std:.4f}, z={z_score:.2f}, "
                f"magnitude={magnitude})"
            )
        elif auto_update and not drifted:
            # Normal value - update baseline
            self.update_baseline(feature_name, current_value)

        return DriftDetectionResult(
            drifted=drifted,
            feature_name=feature_name,
            current_value=current_value,
            baseline_mean=baseline.mean,
            baseline_std=baseline.std,
            z_score=z_score,
            drift_magnitude=magnitude,
        )


# ── Clock Skew Monitoring ────────────────────────────────────────────────────


@dataclass
class ClockSkewCheck:
    """Result of clock skew check."""
    local_time: datetime
    reference_time: Optional[datetime]
    skew_seconds: Optional[float]
    within_tolerance: bool
    error: Optional[str] = None


class ClockSkewMonitor:
    """Monitors clock skew against reference time sources.

    Prevents time-based logic from breaking due to system clock drift.
    Compares local clock against HTTP Date headers from API responses.
    """

    def __init__(
        self,
        *,
        max_skew_seconds: float = 5.0,
        check_interval_seconds: float = 60.0,
    ):
        """Initialize clock skew monitor.

        Args:
            max_skew_seconds: Maximum acceptable skew (default 5s)
            check_interval_seconds: How often to check (default 60s)
        """
        self.max_skew_seconds = max_skew_seconds
        self.check_interval_seconds = check_interval_seconds

        self._last_check: Optional[datetime] = None
        self._last_skew: Optional[float] = None
        self._skew_history: deque = deque(maxlen=100)

        # Stats
        self.total_checks = 0
        self.skew_violations = 0

    def check_skew(
        self,
        reference_time: Optional[datetime] = None,
        *,
        force: bool = False,
    ) -> ClockSkewCheck:
        """Check clock skew against reference time.

        Args:
            reference_time: Reference time from external source (e.g., HTTP Date header)
            force: Force check even if within check_interval

        Returns:
            ClockSkewCheck with skew info
        """
        now = datetime.now(timezone.utc)

        # Rate limit checks
        if not force and self._last_check is not None:
            since_last = (now - self._last_check).total_seconds()
            if since_last < self.check_interval_seconds:
                # Use cached skew
                return ClockSkewCheck(
                    local_time=now,
                    reference_time=None,
                    skew_seconds=self._last_skew,
                    within_tolerance=True if self._last_skew is None else abs(self._last_skew) <= self.max_skew_seconds,
                )

        self.total_checks += 1
        self._last_check = now

        # No reference time provided
        if reference_time is None:
            return ClockSkewCheck(
                local_time=now,
                reference_time=None,
                skew_seconds=None,
                within_tolerance=True,
                error="No reference time available",
            )

        # Ensure timezone-aware
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)

        # Calculate skew (positive = local ahead, negative = local behind)
        skew_seconds = (now - reference_time).total_seconds()
        self._last_skew = skew_seconds
        self._skew_history.append((now, skew_seconds))

        within_tolerance = abs(skew_seconds) <= self.max_skew_seconds

        if not within_tolerance:
            self.skew_violations += 1
            logger.error(
                f"Clock skew violation: {skew_seconds:+.2f}s (tolerance ±{self.max_skew_seconds}s). "
                f"Local={now.isoformat()}, Reference={reference_time.isoformat()}"
            )
        elif abs(skew_seconds) > self.max_skew_seconds * 0.5:
            logger.warning(
                f"Clock skew warning: {skew_seconds:+.2f}s (approaching tolerance ±{self.max_skew_seconds}s)"
            )

        return ClockSkewCheck(
            local_time=now,
            reference_time=reference_time,
            skew_seconds=skew_seconds,
            within_tolerance=within_tolerance,
        )

    def get_recent_skew_stats(self) -> Dict[str, Any]:
        """Get statistics on recent clock skew measurements."""
        if not self._skew_history:
            return {
                "sample_count": 0,
                "mean_skew_seconds": None,
                "max_skew_seconds": None,
                "current_skew_seconds": self._last_skew,
            }

        skews = [s for _, s in self._skew_history]
        return {
            "sample_count": len(skews),
            "mean_skew_seconds": statistics.mean(skews),
            "std_skew_seconds": statistics.stdev(skews) if len(skews) > 1 else 0.0,
            "max_skew_seconds": max(abs(s) for s in skews),
            "current_skew_seconds": skews[-1],
        }


# ── Singletons ───────────────────────────────────────────────────────────────


_timestamp_validator: Optional[TimestampValidator] = None
_drift_detector: Optional[FeatureDriftDetector] = None
_clock_monitor: Optional[ClockSkewMonitor] = None


def get_timestamp_validator() -> TimestampValidator:
    """Get singleton TimestampValidator."""
    global _timestamp_validator
    if _timestamp_validator is None:
        _timestamp_validator = TimestampValidator()
    return _timestamp_validator


def get_drift_detector() -> FeatureDriftDetector:
    """Get singleton FeatureDriftDetector."""
    global _drift_detector
    if _drift_detector is None:
        _drift_detector = FeatureDriftDetector()
    return _drift_detector


def get_clock_monitor() -> ClockSkewMonitor:
    """Get singleton ClockSkewMonitor."""
    global _clock_monitor
    if _clock_monitor is None:
        _clock_monitor = ClockSkewMonitor()
    return _clock_monitor
