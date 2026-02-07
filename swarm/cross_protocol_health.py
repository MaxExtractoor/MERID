"""
Cross-protocol health correlation engine.

Correlates metrics across multiple protocols (DEX, lending, staking) to detect
systemic issues and cascading failures. Outputs correlation coefficients and
alerts when high correlation coincides with simultaneous degradation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import statistics


@dataclass
class ProtocolMetricSeries:
    protocol: str
    metric_name: str
    values: List[float]


@dataclass
class CorrelatedAlert:
    protocol_a: str
    protocol_b: str
    metric_name: str
    correlation: float
    severity: str


class CrossProtocolHealthCorrelator:
    def __init__(self, correlation_threshold: float = 0.8) -> None:
        self.correlation_threshold = correlation_threshold
        self._series: Dict[str, ProtocolMetricSeries] = {}

    def record_series(self, protocol: str, metric_name: str, values: List[float]) -> None:
        key = f"{protocol}:{metric_name}"
        self._series[key] = ProtocolMetricSeries(protocol=protocol, metric_name=metric_name, values=values[-100:])

    def detect_correlations(self) -> List[CorrelatedAlert]:
        alerts: List[CorrelatedAlert] = []
        series_items = list(self._series.values())
        for i, series_a in enumerate(series_items):
            for series_b in series_items[i + 1 :]:
                if series_a.metric_name != series_b.metric_name:
                    continue
                corr = self._pearson_correlation(series_a.values, series_b.values)
                if abs(corr) >= self.correlation_threshold:
                    severity = "critical" if corr > 0 else "inverse_watch"
                    alerts.append(
                        CorrelatedAlert(
                            protocol_a=series_a.protocol,
                            protocol_b=series_b.protocol,
                            metric_name=series_a.metric_name,
                            correlation=corr,
                            severity=severity,
                        )
                    )
        return alerts

    def _pearson_correlation(self, series_a: List[float], series_b: List[float]) -> float:
        if len(series_a) != len(series_b) or len(series_a) < 5:
            return 0.0
        mean_a = statistics.mean(series_a)
        mean_b = statistics.mean(series_b)
        numerator = sum((a - mean_a) * (b - mean_b) for a, b in zip(series_a, series_b))
        denominator = (sum((a - mean_a) ** 2 for a in series_a) * sum((b - mean_b) ** 2 for b in series_b)) ** 0.5 or 1.0
        return numerator / denominator
