"""
Reconciliation Severity Matrix

Defines explicit thresholds for assigning severity (critical vs warning) to
position discrepancies based on contract count and percentage size difference.

This matrix is the single source of truth for discrepancy severity assignment
across all venues. It ensures consistent, auditable severity classification.

Severity Levels:
- CRITICAL: Discrepancy that blocks trading (e.g., large position mismatch, side inversion)
- WARNING: Discrepancy that allows reduced trading (e.g., small position mismatch)
"""

from dataclasses import dataclass
from typing import Optional, Tuple
from enum import Enum


class DiscrepancySeverity(str, Enum):
    """Severity levels for position discrepancies."""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class SeverityThresholds:
    """Thresholds for discrepancy severity classification."""
    
    # Contract count thresholds
    CRITICAL_CONTRACT_COUNT: int = 5  # 5+ contracts = critical
    WARNING_CONTRACT_COUNT: int = 1   # 1-4 contracts = warning
    
    # Percentage thresholds (relative to position size)
    CRITICAL_PERCENT_DIFF: float = 0.20  # 20%+ difference = critical
    WARNING_PERCENT_DIFF: float = 0.10  # 10%+ difference = warning
    
    # Side inversion is always critical
    SIDE_INVERSION_CRITICAL: bool = True
    
    # Phantom position (internal has position, external doesn't) is always critical
    PHANTOM_CRITICAL: bool = True


@dataclass
class DiscrepancyMetrics:
    """Metrics for a position discrepancy."""
    
    # Position deltas
    yes_delta: int  # Internal YES - External YES
    no_delta: int   # Internal NO - External NO
    
    # Position sizes for percentage calculation
    internal_yes_qty: int
    internal_no_qty: int
    external_yes_qty: int
    external_no_qty: int
    
    def total_delta_contracts(self) -> int:
        """Total contract delta (absolute)."""
        return abs(self.yes_delta) + abs(self.no_delta)
    
    def total_internal_contracts(self) -> int:
        """Total internal contracts."""
        return self.internal_yes_qty + self.internal_no_qty
    
    def total_external_contracts(self) -> int:
        """Total external contracts."""
        return self.external_yes_qty + self.external_no_qty
    
    def has_side_inversion(self) -> bool:
        """Check if this is a side inversion (YES vs NO mismatch)."""
        # Side inversion: internal YES > 0 and external NO > 0 (or vice versa)
        return (self.yes_delta > 0 and self.no_delta < 0) or (self.yes_delta < 0 and self.no_delta > 0)
    
    def is_phantom(self) -> bool:
        """Check if this is a phantom position (internal has position, external doesn't)."""
        return (self.total_internal_contracts() > 0 and self.total_external_contracts() == 0)


def calculate_severity(
    metrics: DiscrepancyMetrics,
    thresholds: Optional[SeverityThresholds] = None,
) -> DiscrepancySeverity:
    """
    Calculate discrepancy severity based on metrics and thresholds.
    
    Args:
        metrics: Discrepancy metrics (deltas, position sizes)
        thresholds: Optional custom thresholds (defaults to standard thresholds)
    
    Returns:
        DiscrepancySeverity: CRITICAL, WARNING, or INFO
    
    Severity Assignment Logic:
    1. Side inversion → CRITICAL
    2. Phantom position → CRITICAL
    3. Contract count >= CRITICAL_CONTRACT_COUNT → CRITICAL
    4. Percentage diff >= CRITICAL_PERCENT_DIFF → CRITICAL
    5. Contract count >= WARNING_CONTRACT_COUNT → WARNING
    6. Percentage diff >= WARNING_PERCENT_DIFF → WARNING
    7. Otherwise → INFO (no discrepancy or negligible)
    """
    if thresholds is None:
        thresholds = SeverityThresholds()
    
    # Check for critical conditions first
    
    # Side inversion is always critical
    if metrics.has_side_inversion() and thresholds.SIDE_INVERSION_CRITICAL:
        return DiscrepancySeverity.CRITICAL
    
    # Phantom position is always critical
    if metrics.is_phantom() and thresholds.PHANTOM_CRITICAL:
        return DiscrepancySeverity.CRITICAL
    
    # Check contract count threshold
    total_delta = metrics.total_delta_contracts()
    if total_delta >= thresholds.CRITICAL_CONTRACT_COUNT:
        return DiscrepancySeverity.CRITICAL
    elif total_delta >= thresholds.WARNING_CONTRACT_COUNT:
        return DiscrepancySeverity.WARNING
    
    # Check percentage difference threshold
    percent_diff = calculate_percentage_diff(metrics)
    if percent_diff >= thresholds.CRITICAL_PERCENT_DIFF:
        return DiscrepancySeverity.CRITICAL
    elif percent_diff >= thresholds.WARNING_PERCENT_DIFF:
        return DiscrepancySeverity.WARNING
    
    # No significant discrepancy
    return DiscrepancySeverity.INFO


def calculate_percentage_diff(metrics: DiscrepancyMetrics) -> float:
    """
    Calculate percentage difference between internal and external positions.
    
    Returns:
        float: Percentage difference (0.0 to 1.0)
    
    Formula: |internal - external| / max(internal, external)
    """
    internal_total = metrics.total_internal_contracts()
    external_total = metrics.total_external_contracts()
    
    # Avoid division by zero
    if internal_total == 0 and external_total == 0:
        return 0.0
    
    max_contracts = max(internal_total, external_total)
    if max_contracts == 0:
        return 0.0
    
    delta = abs(internal_total - external_total)
    return delta / max_contracts


def get_severity_reason(
    metrics: DiscrepancyMetrics,
    severity: DiscrepancySeverity,
    thresholds: Optional[SeverityThresholds] = None,
) -> str:
    """
    Get human-readable reason for severity assignment.
    
    Args:
        metrics: Discrepancy metrics
        severity: Assigned severity
        thresholds: Optional custom thresholds
    
    Returns:
        str: Human-readable reason
    """
    if thresholds is None:
        thresholds = SeverityThresholds()
    
    if severity == DiscrepancySeverity.INFO:
        return "Positions match (no significant discrepancy)"
    
    reasons = []
    
    if metrics.has_side_inversion() and thresholds.SIDE_INVERSION_CRITICAL:
        reasons.append("side inversion (YES vs NO mismatch)")
    
    if metrics.is_phantom() and thresholds.PHANTOM_CRITICAL:
        reasons.append("phantom position (internal has position, external doesn't)")
    
    total_delta = metrics.total_delta_contracts()
    if total_delta >= thresholds.CRITICAL_CONTRACT_COUNT:
        reasons.append(f"large contract delta ({total_delta} contracts)")
    elif total_delta >= thresholds.WARNING_CONTRACT_COUNT:
        reasons.append(f"small contract delta ({total_delta} contracts)")
    
    percent_diff = calculate_percentage_diff(metrics)
    if percent_diff >= thresholds.CRITICAL_PERCENT_DIFF:
        reasons.append(f"large percentage diff ({percent_diff:.1%})")
    elif percent_diff >= thresholds.WARNING_PERCENT_DIFF:
        reasons.append(f"small percentage diff ({percent_diff:.1%})")
    
    if not reasons:
        reasons.append("unknown discrepancy")
    
    return "; ".join(reasons)


# Default thresholds instance
DEFAULT_THRESHOLDS = SeverityThresholds()
