"""Onboarding and routing risk metrics helpers.

The helpers in this module intentionally stay dependency-light so they can be
used from notebooks, tests, or lightweight CLI tooling without pulling in
pandas. All calculations operate on built-in Python types such as ``dict``
and ``list``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple


class OnboardingRiskExceeded(RuntimeError):
    """Raised when a risk metric breaches the configured threshold."""


@dataclass(frozen=True)
class SegmentRecord:
    """Input data for a segment-level onboarding computation."""

    segment: str
    starts: int
    abandoned: int
    avg_annual_revenue: float
    expected_years: float


@dataclass(frozen=True)
class SegmentMetrics:
    """Computed metrics for a segment."""

    segment: str
    abandonment_rate: float
    estimated_cltv: float
    estimated_lost_revenue: float


@dataclass(frozen=True)
class RoutingSnapshot:
    """Aggregated routing/execution stats for a venue or product."""

    name: str
    total_orders: int
    mismatches: int
    avg_slippage_bps: float
    p95_route_latency_ms: float


@dataclass(frozen=True)
class StepDropoffMetrics:
    """Drop-off and revenue-at-risk metrics for a funnel step."""

    step: str
    start: int
    complete: int
    dropoff_ratio: float
    revenue_at_risk: float


def _safe_ratio(numerator: float, denominator: float) -> float:
    """Return numerator / denominator guarding against divide-by-zero."""

    if denominator == 0:
        return 0.0
    return numerator / denominator


def compute_segment_metrics(
    records: Iterable[SegmentRecord],
    *,
    abandonment_threshold: float | None = None,
) -> List[SegmentMetrics]:
    """Compute abandonment rate, CLTV, and lost revenue per segment.

    Args:
        records: Iterable of ``SegmentRecord`` entries.
        abandonment_threshold: Optional threshold (0-1). If provided and any
            segment's abandonment rate exceeds it, an ``OnboardingRiskExceeded``
            is raised so the caller can fail fast in CI.
    """

    metrics: List[SegmentMetrics] = []
    worst_rate = 0.0

    for record in records:
        cltv = record.avg_annual_revenue * record.expected_years
        abandonment_rate = _safe_ratio(record.abandoned, record.starts)
        lost_revenue = abandonment_rate * record.starts * cltv
        metrics.append(
            SegmentMetrics(
                segment=record.segment,
                abandonment_rate=abandonment_rate,
                estimated_cltv=cltv,
                estimated_lost_revenue=lost_revenue,
            )
        )
        worst_rate = max(worst_rate, abandonment_rate)

    if abandonment_threshold is not None and worst_rate > abandonment_threshold:
        raise OnboardingRiskExceeded(
            f"Abandonment rate {worst_rate:.2%} exceeds threshold {abandonment_threshold:.2%}"
        )

    return metrics


def compute_step_dropoff_metrics(
    steps: Iterable[Dict[str, int]],
    *,
    arr_per_client: float,
) -> List[StepDropoffMetrics]:
    """Compute drop-off ratio and revenue at risk per onboarding step."""

    results: List[StepDropoffMetrics] = []
    for step in steps:
        name = step.get("step") or step.get("name")
        if name is None:
            raise KeyError("Each step entry must include a 'step' key")
        start = int(step.get("start", 0))
        complete = int(step.get("complete", 0))
        dropoff = _safe_ratio(start - complete, start)
        revenue_at_risk = dropoff * start * arr_per_client
        results.append(
            StepDropoffMetrics(
                step=name,
                start=start,
                complete=complete,
                dropoff_ratio=dropoff,
                revenue_at_risk=revenue_at_risk,
            )
        )

    return results


def enforce_funnel_monotonicity(
    steps: Iterable[Dict[str, int]],
    *,
    tolerance: float = 0.02,
) -> None:
    """Ensure onboarding funnel steps do not unexpectedly grow upstream volume.

    Args:
        steps: Iterable of onboarding step dictionaries.
        tolerance: Allowable relative increase (defaults to 2%) to account for
            minor instrumentation noise. Any increase larger than this indicates
            potential duplication or corruption and raises ``OnboardingRiskExceeded``.
    """

    last_start: float | None = None
    for step in steps:
        start = float(step.get("start", 0))
        if last_start is not None and start > last_start * (1 + tolerance):
            raise OnboardingRiskExceeded(
                "Onboarding funnel start counts increased between steps; check instrumentation"
            )
        last_start = start


def estimate_step_arr_recovery(
    *,
    start: int,
    old_dropoff: float,
    new_dropoff: float,
    arr_per_client: float,
) -> float:
    """Estimate ARR recovered by reducing drop-off at a step."""

    if start < 0:
        raise ValueError("start must be non-negative")
    delta = max(old_dropoff - new_dropoff, 0.0)
    return delta * start * arr_per_client


def compute_ttv_churn_delta(
    cohort_churn: Dict[str, float],
    baseline_cohort: str,
) -> Dict[str, float]:
    """Return churn deltas per cohort bucket vs the baseline cohort."""

    if baseline_cohort not in cohort_churn:
        raise KeyError(f"Baseline cohort '{baseline_cohort}' not found")

    baseline_rate = cohort_churn[baseline_cohort]
    return {
        cohort: churn_rate - baseline_rate for cohort, churn_rate in cohort_churn.items()
    }


def estimate_cltv_loss(
    *,
    cltv_base: float,
    delta_churn: float,
    delay_days: int,
    daily_revenue: float,
) -> float:
    """Estimate CLTV loss for a cohort given churn delta and onboarding delay."""

    adjusted_cltv = cltv_base * (1 - max(delta_churn, 0.0)) - delay_days * daily_revenue
    return max(0.0, cltv_base - adjusted_cltv)


def compute_routing_metrics(
    snapshots: Iterable[RoutingSnapshot],
    *,
    mismatch_threshold: float | None = None,
    slippage_threshold_bps: float | None = None,
) -> List[Tuple[str, float, float]]:
    """Return mismatch rate and average slippage per snapshot.

    Args:
        snapshots: Iterable of routing snapshots.
        mismatch_threshold: Optional ratio (0-1). If the mismatch rate exceeds
            this value for any snapshot, ``OnboardingRiskExceeded`` is raised.
        slippage_threshold_bps: Optional bound for average slippage. If breached,
            ``OnboardingRiskExceeded`` is raised.
    """

    results: List[Tuple[str, float, float]] = []
    for snapshot in snapshots:
        mismatch_rate = _safe_ratio(snapshot.mismatches, snapshot.total_orders)
        slippage_bps = snapshot.avg_slippage_bps
        results.append((snapshot.name, mismatch_rate, slippage_bps))

        if mismatch_threshold is not None and mismatch_rate > mismatch_threshold:
            raise OnboardingRiskExceeded(
                f"Mismatch rate {mismatch_rate:.2%} exceeds threshold for {snapshot.name}"
            )
        if slippage_threshold_bps is not None and slippage_bps > slippage_threshold_bps:
            raise OnboardingRiskExceeded(
                f"Avg slippage {slippage_bps:.2f} bps exceeds threshold for {snapshot.name}"
            )

    return results
