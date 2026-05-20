"""
Alert thresholds configuration for Kalshi audit pipeline validation scripts.

This module defines alert thresholds for validation script outputs.
When thresholds are exceeded, alerts should be triggered (page operators,
halt trading, or log warnings depending on severity).
"""

from dataclasses import dataclass
from enum import Enum


class AlertSeverity(Enum):
    """Alert severity levels."""
    CRITICAL = "critical"  # Page operators, consider halting trading
    HIGH = "high"  # Page operators
    MEDIUM = "medium"  # Log warning
    LOW = "low"  # Log info


@dataclass
class AlertThreshold:
    """Single alert threshold definition."""
    name: str
    metric: str
    threshold: float
    operator: str  # ">", "<", "==", ">=", "<="
    severity: AlertSeverity
    description: str


# Order Construction Validation Thresholds
ORDER_CONSTRUCTION_ALERTS = [
    AlertThreshold(
        name="manifest_missing_ticker",
        metric="tickers_in_logs_not_in_manifest_count",
        threshold=0,
        operator=">",
        severity=AlertSeverity.CRITICAL,
        description="Tickers traded but missing from canonical manifest (semantic drift risk)"
    ),
    AlertThreshold(
        name="side_action_mismatch",
        metric="side_action_mismatch_count",
        threshold=0,
        operator=">",
        severity=AlertSeverity.HIGH,
        description="Orders with side/action mismatch against economic intent"
    ),
    AlertThreshold(
        name="stale_snapshot",
        metric="stale_snapshot_count",
        threshold=5,
        operator=">",
        severity=AlertSeverity.MEDIUM,
        description="Orders with stale snapshots (>90s)"
    ),
    AlertThreshold(
        name="negative_edge",
        metric="negative_edge_count",
        threshold=0,
        operator=">",
        severity=AlertSeverity.HIGH,
        description="Orders with negative edge_pct"
    ),
    AlertThreshold(
        name="invalid_price",
        metric="invalid_price_count",
        threshold=0,
        operator=">",
        severity=AlertSeverity.CRITICAL,
        description="Orders with invalid price_cents (not in 0-100 range)"
    ),
]

# Settlement Validation Thresholds
SETTLEMENT_ALERTS = [
    AlertThreshold(
        name="settlement_without_api_result",
        metric="settlement_without_api_result_count",
        threshold=0,
        operator=">",
        severity=AlertSeverity.CRITICAL,
        description="Settlements without Kalshi API result (strict mode violation)"
    ),
    AlertThreshold(
        name="outcome_mismatch",
        metric="outcome_mismatch_count",
        threshold=0,
        operator=">",
        severity=AlertSeverity.HIGH,
        description="Internal Outcome enum disagrees with Kalshi API market_result"
    ),
    AlertThreshold(
        name="pnl_direction_mismatch",
        metric="pnl_direction_mismatch_count",
        threshold=0,
        operator=">",
        severity=AlertSeverity.HIGH,
        description="P&L direction doesn't match market result (e.g., YES won but lost money)"
    ),
    AlertThreshold(
        name="unknown_outcome_with_pnl",
        metric="unknown_outcome_with_pnl_count",
        threshold=0,
        operator=">",
        severity=AlertSeverity.MEDIUM,
        description="Non-zero P&L but internal Outcome is UNKNOWN"
    ),
]

# Lifecycle Funnel Thresholds
LIFECYCLE_FUNNEL_ALERTS = [
    AlertThreshold(
        name="strategy_gate_drop_rate",
        metric="strategy_gate_drop_rate",
        threshold=0.5,
        operator=">",
        severity=AlertSeverity.MEDIUM,
        description="More than 50% of signals dropped at strategy gate"
    ),
    AlertThreshold(
        name="risk_gate_drop_rate",
        metric="risk_gate_drop_rate",
        threshold=0.3,
        operator=">",
        severity=AlertSeverity.HIGH,
        description="More than 30% of approved signals dropped at risk gate"
    ),
    AlertThreshold(
        name="order_to_fill_drop_rate",
        metric="order_to_fill_drop_rate",
        threshold=0.1,
        operator=">",
        severity=AlertSeverity.HIGH,
        description="More than 10% of orders not filled"
    ),
    AlertThreshold(
        name="fill_to_settle_drop_rate",
        metric="fill_to_settle_drop_rate",
        threshold=0.05,
        operator=">",
        severity=AlertSeverity.MEDIUM,
        description="More than 5% of fills not settled"
    ),
]

# Internal Mapping Check Thresholds
INTERNAL_MAPPING_ALERTS = [
    AlertThreshold(
        name="missing_from_manifest_rate",
        metric="missing_from_manifest_rate",
        threshold=0.01,
        operator=">",
        severity=AlertSeverity.HIGH,
        description="More than 1% of traded tickers missing from manifest"
    ),
    AlertThreshold(
        name="manifest_drift",
        metric="manifest_drift_count",
        threshold=0,
        operator=">",
        severity=AlertSeverity.MEDIUM,
        description="Manifest entries never traded (config drift)"
    ),
]

# Kill-Switch/Risk Interaction Thresholds
KILL_SWITCH_ALERTS = [
    AlertThreshold(
        name="would_have_won_rate",
        metric="would_have_won_rate",
        threshold=0.6,
        operator=">",
        severity=AlertSeverity.HIGH,
        description="More than 60% of killed trades would have won (risk gates too aggressive)"
    ),
    AlertThreshold(
        name="kill_rate",
        metric="kill_rate",
        threshold=0.2,
        operator=">",
        severity=AlertSeverity.MEDIUM,
        description="More than 20% of trades killed (high friction)"
    ),
]

# Edge Calibration Thresholds
EDGE_CALIBRATION_ALERTS = [
    AlertThreshold(
        name="low_edge_win_rate",
        metric="low_edge_win_rate",
        threshold=0.4,
        operator="<",
        severity=AlertSeverity.MEDIUM,
        description="Win rate for 0-2% edge bucket below 40% (edge estimates too optimistic)"
    ),
    AlertThreshold(
        name="high_edge_win_rate",
        metric="high_edge_win_rate",
        threshold=0.55,
        operator="<",
        severity=AlertSeverity.MEDIUM,
        description="Win rate for 10%+ edge bucket below 55% (edge estimates too optimistic)"
    ),
]

# Per-Agent Metrics Thresholds
PER_AGENT_ALERTS = [
    AlertThreshold(
        name="agent_win_rate",
        metric="agent_win_rate",
        threshold=0.45,
        operator="<",
        severity=AlertSeverity.MEDIUM,
        description="Agent win rate below 45%"
    ),
    AlertThreshold(
        name="agent_sharpe_ratio",
        metric="agent_sharpe_ratio",
        threshold=0.5,
        operator="<",
        severity=AlertSeverity.HIGH,
        description="Agent Sharpe ratio below 0.5"
    ),
    AlertThreshold(
        name="window_utilization",
        metric="window_utilization",
        threshold=0.1,
        operator="<",
        severity=AlertSeverity.LOW,
        description="Agent window utilization below 10% (under-utilized)"
    ),
]


def check_thresholds(metrics: dict, threshold_list: list) -> list:
    """Check metrics against threshold list.
    
    Args:
        metrics: Dict of metric_name -> value
        threshold_list: List of AlertThreshold objects
        
    Returns:
        List of triggered alerts
    """
    triggered = []
    
    for threshold in threshold_list:
        metric_value = metrics.get(threshold.metric)
        if metric_value is None:
            continue
        
        # Evaluate threshold
        triggered_flag = False
        if threshold.operator == ">":
            triggered_flag = metric_value > threshold.threshold
        elif threshold.operator == "<":
            triggered_flag = metric_value < threshold.threshold
        elif threshold.operator == ">=":
            triggered_flag = metric_value >= threshold.threshold
        elif threshold.operator == "<=":
            triggered_flag = metric_value <= threshold.threshold
        elif threshold.operator == "==":
            triggered_flag = metric_value == threshold.threshold
        
        if triggered_flag:
            triggered.append({
                'name': threshold.name,
                'severity': threshold.severity.value,
                'metric': threshold.metric,
                'value': metric_value,
                'threshold': threshold.threshold,
                'description': threshold.description,
            })
    
    return triggered


def get_all_thresholds():
    """Get all threshold definitions."""
    return {
        'order_construction': ORDER_CONSTRUCTION_ALERTS,
        'settlement': SETTLEMENT_ALERTS,
        'lifecycle_funnel': LIFECYCLE_FUNNEL_ALERTS,
        'internal_mapping': INTERNAL_MAPPING_ALERTS,
        'kill_switch': KILL_SWITCH_ALERTS,
        'edge_calibration': EDGE_CALIBRATION_ALERTS,
        'per_agent': PER_AGENT_ALERTS,
    }


if __name__ == "__main__":
    # Example usage
    print("Alert Thresholds Configuration")
    print("=" * 70)
    
    all_thresholds = get_all_thresholds()
    for category, thresholds in all_thresholds.items():
        print(f"\n{category.upper()}:")
        print("-" * 70)
        for t in thresholds:
            print(f"  {t.name}:")
            print(f"    Metric: {t.metric}")
            print(f"    Threshold: {t.operator} {t.threshold}")
            print(f"    Severity: {t.severity.value}")
            print(f"    Description: {t.description}")
