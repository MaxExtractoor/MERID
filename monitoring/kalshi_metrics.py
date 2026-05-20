"""Kalshi Metrics Exporter - Prometheus-compatible metrics for Kalshi trading.

Exports metrics for:
- Circuit breaker state
- API latency (histogram)
- API errors and request rates
- Order execution metrics
- Kill switch state
- Regime detection
- Correlation risk

Integrates with monitoring.metrics for Prometheus scraping.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from monitoring.metrics import Counter, Gauge, Histogram, MetricValue
from utils.logger import get_logger
from merid.event_venues.kalshi.order_errors import KalshiOrderErrorCode

logger = get_logger("monitoring.kalshi_metrics")


@dataclass
class KalshiMetricsCollector:
    """Collects and exports Kalshi-specific metrics for Prometheus.
    
    Usage:
        collector = KalshiMetricsCollector()
        
        # Record API call
        collector.record_api_call(latency_ms=150, success=True)
        
        # Record order
        collector.record_order(status="filled", count=10)
        
        # Update circuit breaker state
        collector.set_circuit_breaker_state("closed")
        
        # Export metrics
        metrics = collector.collect()
    """
    
    def __init__(self) -> None:
        # Circuit breaker metrics
        self.circuit_breaker_open = Gauge(
            "kalshi_circuit_breaker_open",
            "1 if Kalshi circuit breaker is open",
            ["venue"]
        )
        self.circuit_breaker_half_open = Gauge(
            "kalshi_circuit_breaker_half_open",
            "1 if Kalshi circuit breaker is half-open",
            ["venue"]
        )
        
        # API metrics
        self.api_requests = Counter(
            "kalshi_api_requests_total",
            "Total Kalshi API requests",
            ["method", "endpoint"]
        )
        self.api_errors = Counter(
            "kalshi_api_errors_total",
            "Total Kalshi API errors",
            ["method", "endpoint", "error_type"]
        )
        self.api_latency = Histogram(
            "kalshi_api_latency_seconds",
            "Kalshi API latency in seconds",
            ["method", "endpoint"],
            buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
        )
        
        # Order metrics
        self.orders_total = Counter(
            "kalshi_orders_total",
            "Total orders submitted",
            ["mode", "status"]
        )
        self.orders_rejected = Counter(
            "kalshi_orders_rejected_total",
            "Total orders rejected",
            ["error_code", "severity", "category"]
        )
        self.order_latency = Histogram(
            "kalshi_order_latency_seconds",
            "Order placement latency",
            ["mode"],
            buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
        )
        
        # Kill switch
        self.kill_switch_active = Gauge(
            "kalshi_kill_switch_active",
            "1 if Kalshi kill switch is active"
        )
        
        # Risk metrics
        self.daily_pnl = Gauge(
            "kalshi_daily_pnl_usd",
            "Daily PnL in USD"
        )
        self.drawdown_pct = Gauge(
            "kalshi_drawdown_percentage",
            "Current drawdown percentage"
        )
        
        # Risk envelope metrics
        self.envelope_band = Gauge(
            "kalshi_risk_envelope_band",
            "Current risk envelope band (1.0, 0.75, 0.5, 0.25, 0.0)",
            ["profile"]
        )
        self.envelope_distance_to_halt_pct = Gauge(
            "kalshi_risk_envelope_distance_to_halt_pct",
            "Remaining headroom before halt as percentage",
            ["profile"]
        )
        self.envelope_per_trade_multiplier = Gauge(
            "kalshi_risk_envelope_per_trade_multiplier",
            "Current per-trade risk multiplier applied to base risk",
            ["profile"]
        )
        
        # Regime metrics
        self.regime_active = Gauge(
            "kalshi_regime",
            "1 if regime is active",
            ["asset", "regime"]
        )
        self.regime_confidence = Gauge(
            "kalshi_regime_confidence",
            "Regime detection confidence (0-1)",
            ["asset", "regime"]
        )
        
        # Correlation metrics
        self.correlation_max = Gauge(
            "kalshi_correlation_max",
            "Maximum inter-asset correlation"
        )
        self.correlation_pairs = Gauge(
            "kalshi_correlation",
            "Correlation between asset pairs",
            ["asset_a", "asset_b"]
        )

        # WebSocket health metrics
        self.ws_connection_state = Gauge(
            "kalshi_ws_connection_state",
            "1 if Kalshi WebSocket is connected"
        )
        self.ws_reconnects = Counter(
            "kalshi_ws_reconnects_total",
            "Total Kalshi WebSocket reconnect attempts"
        )

        self.catalog_last_refresh_timestamp = Gauge(
            "kalshi_catalog_last_refresh_timestamp",
            "UTC epoch seconds of the last catalog refresh"
        )

        self.cb_triggers = Counter(
            "kalshi_cb_triggers_total",
            "Kalshi circuit breaker openings by error code and category",
            ["error_code", "category"],
        )
        
        # Latency monitor integration
        self.latency_warnings = Counter(
            "kalshi_latency_warnings_total",
            "Total latency warning threshold breaches"
        )
        self.latency_critical = Counter(
            "kalshi_latency_critical_total",
            "Total latency critical threshold breaches"
        )
        
        self._lock = threading.Lock()
        self._last_collect = 0.0
        
    def record_api_call(
        self,
        method: str,
        endpoint: str,
        latency_ms: float,
        success: bool,
        error_type: Optional[str] = None
    ) -> None:
        """Record an API call with latency and success status."""
        latency_s = latency_ms / 1000.0
        
        with self._lock:
            self.api_requests.inc(1, {"method": method, "endpoint": endpoint})
            self.api_latency.observe(latency_s, {"method": method, "endpoint": endpoint})
            
            if not success:
                self.api_errors.inc(1, {
                    "method": method,
                    "endpoint": endpoint,
                    "error_type": error_type or "unknown"
                })
    
    def record_order(
        self,
        mode: str,
        status: str,
        count: int = 1,
        latency_ms: Optional[float] = None,
        error_code: Optional[str] = None
    ) -> None:
        """Record an order execution."""
        with self._lock:
            self.orders_total.inc(count, {"mode": mode, "status": status})
            
            if status == "rejected" and error_code:
                code_value, severity, category = _derive_error_labels(error_code)
                self.orders_rejected.inc(1, {
                    "error_code": code_value,
                    "severity": severity,
                    "category": category,
                })
            
            if latency_ms is not None:
                self.order_latency.observe(latency_ms / 1000.0, {"mode": mode})
    
    def set_circuit_breaker_state(self, state: str) -> None:
        """Update circuit breaker state metrics."""
        with self._lock:
            if state == "open":
                self.circuit_breaker_open.set(1, {"venue": "kalshi"})
                self.circuit_breaker_half_open.set(0, {"venue": "kalshi"})
            elif state == "half_open":
                self.circuit_breaker_open.set(0, {"venue": "kalshi"})
                self.circuit_breaker_half_open.set(1, {"venue": "kalshi"})
            else:  # closed
                self.circuit_breaker_open.set(0, {"venue": "kalshi"})
                self.circuit_breaker_half_open.set(0, {"venue": "kalshi"})
    
    def set_kill_switch(self, active: bool) -> None:
        """Update kill switch state."""
        with self._lock:
            self.kill_switch_active.set(1 if active else 0)
    
    def set_risk_metrics(self, daily_pnl: float, drawdown_pct: float) -> None:
        """Update risk metrics."""
        with self._lock:
            self.daily_pnl.set(daily_pnl)
            self.drawdown_pct.set(drawdown_pct)
    
    def set_regime(
        self,
        asset: str,
        regime: str,
        confidence: float,
        active: bool = True
    ) -> None:
        """Update regime detection metrics."""
        with self._lock:
            self.regime_active.set(1 if active else 0, {"asset": asset, "regime": regime})
            self.regime_confidence.set(confidence, {"asset": asset, "regime": regime})
    
    def set_correlation(self, asset_a: str, asset_b: str, correlation: float) -> None:
        """Update correlation metric for an asset pair."""
        with self._lock:
            self.correlation_pairs.set(abs(correlation), {"asset_a": asset_a, "asset_b": asset_b})
    
    def set_max_correlation(self, max_corr: float) -> None:
        """Update maximum correlation across all pairs."""
        with self._lock:
            self.correlation_max.set(max_corr)
    
    def record_latency_alert(self, severity: str) -> None:
        """Record a latency threshold breach."""
        with self._lock:
            if severity == "warning":
                self.latency_warnings.inc(1)
            elif severity == "critical":
                self.latency_critical.inc(1)

    def set_ws_connection_state(self, connected: bool) -> None:
        """Update the WebSocket connection state gauge."""
        with self._lock:
            self.ws_connection_state.set(1 if connected else 0)

    def record_ws_reconnect(self, count: int = 1) -> None:
        """Increment the WebSocket reconnect counter."""
        with self._lock:
            self.ws_reconnects.inc(count)

    def set_catalog_refresh_timestamp(self, timestamp: float) -> None:
        """Record the epoch seconds of the latest catalog refresh."""
        with self._lock:
            self.catalog_last_refresh_timestamp.set(timestamp)
    
    def collect(self) -> List[MetricValue]:
        """Collect all metrics for Prometheus export."""
        with self._lock:
            metrics: List[MetricValue] = []
            
            # Collect from all metric objects
            for attr_name in dir(self):
                # Skip private attributes and methods
                if attr_name.startswith('_'):
                    continue
                    
                attr = getattr(self, attr_name)
                
                # Only collect from metric objects, not methods
                if hasattr(attr, 'collect') and not callable(attr):
                    try:
                        collected = attr.collect()
                        if isinstance(collected, list):
                            metrics.extend(collected)
                        else:
                            metrics.append(collected)
                    except Exception as e:
                        logger.warning(f"Failed to collect from {attr_name}: {e}")
            
            self._last_collect = time.time()
            return metrics
    
    def to_prometheus_format(self) -> str:
        """Export metrics in Prometheus text format."""
        lines: List[str] = []
        
        for metric in self.collect():
            # Help line
            if metric.help_text:
                lines.append(f"# HELP {metric.name} {metric.help_text}")
            
            # Type line
            lines.append(f"# TYPE {metric.name} {metric.metric_type.value}")
            
            # Value line
            labels_str = ",".join([f'{k}="{v}"' for k, v in metric.labels.items()]) if metric.labels else ""
            if labels_str:
                lines.append(f"{metric.name}{{{labels_str}}} {metric.value}")
            else:
                lines.append(f"{metric.name} {metric.value}")
        
        return "\n".join(lines)


def _derive_error_labels(error_code: str) -> Tuple[str, str, str]:
    """Resolve severity/category from KalshiOrderErrorCode."""

    code = KalshiOrderErrorCode.from_string(error_code)
    return code.value, code.severity, code.category


# ── Singleton ────────────────────────────────────────────────────────────

_collector: Optional[KalshiMetricsCollector] = None
_lock = threading.Lock()


def get_kalshi_metrics_collector() -> KalshiMetricsCollector:
    """Get the singleton KalshiMetricsCollector."""
    global _collector
    if _collector is None:
        with _lock:
            if _collector is None:
                _collector = KalshiMetricsCollector()
    return _collector


# ── Convenience Functions ────────────────────────────────────────────────

def record_kalshi_api_call(
    method: str,
    endpoint: str,
    latency_ms: float,
    success: bool,
    error_type: Optional[str] = None
) -> None:
    """Record an API call to the global collector."""
    get_kalshi_metrics_collector().record_api_call(
        method, endpoint, latency_ms, success, error_type
    )


def record_kalshi_order(
    mode: str,
    status: str,
    count: int = 1,
    latency_ms: Optional[float] = None,
    error_code: Optional[str] = None
) -> None:
    """Record an order to the global collector."""
    get_kalshi_metrics_collector().record_order(
        mode, status, count, latency_ms, error_code
    )


def set_kalshi_circuit_breaker(state: str) -> None:
    """Update circuit breaker state in global collector."""
    get_kalshi_metrics_collector().set_circuit_breaker_state(state)


def set_kalshi_kill_switch(active: bool) -> None:
    """Update kill switch state in global collector."""
    get_kalshi_metrics_collector().set_kill_switch(active)


def set_kalshi_risk_metrics(daily_pnl: float, drawdown_pct: float) -> None:
    """Update risk metrics in global collector."""
    get_kalshi_metrics_collector().set_risk_metrics(daily_pnl, drawdown_pct)


def set_kalshi_ws_connection_state(connected: bool) -> None:
    """Update Kalshi WebSocket connection state gauge."""
    get_kalshi_metrics_collector().set_ws_connection_state(connected)


def record_kalshi_ws_reconnect(count: int = 1) -> None:
    """Increment the Kalshi WebSocket reconnect counter."""
    get_kalshi_metrics_collector().record_ws_reconnect(count)


def record_kalshi_cb_trigger(error_code: KalshiOrderErrorCode | None) -> None:
    """Record an attribution label for Kalshi circuit breaker opens."""
    labels = {
        "error_code": "unknown",
        "category": "unknown",
    }

    if error_code:
        labels["error_code"] = error_code.name.lower()
        labels["category"] = error_code.category

    get_kalshi_metrics_collector().cb_triggers.inc(1, labels)


def set_kalshi_catalog_refresh_timestamp(timestamp: float) -> None:
    """Record the epoch timestamp of the latest catalog refresh."""
    get_kalshi_metrics_collector().set_catalog_refresh_timestamp(timestamp)
