"""
Sentiment/Volatility/Sizing Metrics Exporter

Prometheus-compatible metrics for runtime monitoring of the Fear/Greed,
Volatility & Sizing lane.

Provides:
- Gauge metrics for current sentiment, volatility, and sizing multiplier
- Counter metrics for regime transitions and alert firings
- Histogram metrics for sizing multiplier distribution
- Health check metrics for data staleness
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

try:
    from prometheus_client import Gauge, Counter, Histogram, Info, CollectorRegistry
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    # Dummy classes for when prometheus_client is not available
    class _DummyMetric:
        def __init__(self, *args, **kwargs): pass
        def set(self, *args, **kwargs): pass
        def inc(self, *args, **kwargs): pass
        def observe(self, *args, **kwargs): pass
        def info(self, *args, **kwargs): pass
    
    Gauge = Counter = Histogram = Info = _DummyMetric
    CollectorRegistry = lambda: None

from utils.logger import get_logger

logger = get_logger("merid.prediction.risk.sentiment_vol_metrics")


# ═══════════════════════════════════════════════════════════════════════════
# Prometheus Metrics Definitions
# ═══════════════════════════════════════════════════════════════════════════

# Current values (gauges)
SENTIMENT_VALUE = Gauge(
    "merid_sentiment_value",
    "Current fear/greed index (0-100)",
    ["asset"]
)

SENTIMENT_CONFIDENCE = Gauge(
    "merid_sentiment_confidence",
    "Confidence in sentiment reading (0-1)",
    ["asset"]
)

SENTIMENT_REGIME = Gauge(
    "merid_sentiment_regime",
    "Sentiment regime as numeric value (0=extreme_fear, 4=extreme_greed)",
    ["asset"]
)

VOLATILITY_VALUE = Gauge(
    "merid_volatility_value",
    "Current annualized volatility as percentage",
    ["asset"]
)

VOLATILITY_UNCERTAINTY = Gauge(
    "merid_volatility_uncertainty",
    "Vol-of-vol uncertainty penalty (0-1)",
    ["asset"]
)

VOLATILITY_REGIME = Gauge(
    "merid_volatility_regime",
    "Volatility regime as numeric value (0=dead, 4=extreme)",
    ["asset"]
)

SIZING_MULTIPLIER = Gauge(
    "merid_sizing_multiplier",
    "Current sizing multiplier applied to positions",
    ["asset", "is_contrarian"]
)

SIZING_REGIME_LABEL = Gauge(
    "merid_sizing_regime_label",
    "Sizing regime label (0=NORMAL, 1=CAUTION, 2=HALTED)",
    ["asset"]
)

# Counters for regime transitions
REGIME_TRANSITIONS = Counter(
    "merid_regime_transitions_total",
    "Total regime transitions by type",
    ["asset", "regime_type", "from_regime", "to_regime"]
)

ALERTS_FIRED = Counter(
    "merid_sentiment_vol_alerts_fired_total",
    "Total alerts fired by type",
    ["alert_type", "severity", "asset"]
)

# Histograms for distribution tracking
SIZING_MULTIPLIER_DISTRIBUTION = Histogram(
    "merid_sizing_multiplier_distribution",
    "Distribution of sizing multiplier values",
    ["asset"],
    buckets=[0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2]
)

SENTIMENT_VALUE_DISTRIBUTION = Histogram(
    "merid_sentiment_value_distribution",
    "Distribution of sentiment values",
    ["asset"],
    buckets=[0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
)

VOLATILITY_DISTRIBUTION = Histogram(
    "merid_volatility_distribution",
    "Distribution of annualized volatility values",
    ["asset"],
    buckets=[0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0]
)

# Data quality metrics
DATA_STALENESS_SECONDS = Gauge(
    "merid_sentiment_vol_data_staleness_seconds",
    "Seconds since last data update",
    ["asset", "data_type"]
)

DATA_QUALITY_SCORE = Gauge(
    "merid_sentiment_vol_data_quality_score",
    "Overall data quality score (0-1)",
    ["asset"]
)

# Service health
SERVICE_UPDATE_COUNT = Counter(
    "merid_sentiment_vol_service_updates_total",
    "Total number of service update cycles",
    ["result"]
)

SERVICE_ERROR_COUNT = Counter(
    "merid_sentiment_vol_service_errors_total",
    "Total number of service errors",
    ["error_type"]
)

# Info metric for version/config
CONFIG_INFO = Info(
    "merid_sentiment_vol_config",
    "Configuration information for sentiment/volatility sizing"
)


# ═══════════════════════════════════════════════════════════════════════════
# Metrics Recorder
# ═══════════════════════════════════════════════════════════════════════════

class SentimentVolMetricsRecorder:
    """
    Recorder for sentiment/volatility/sizing metrics.
    
    Call this from the SentimentVolService to update metrics
    whenever data changes.
    """
    
    def __init__(self):
        self._last_regimes: Dict[str, Dict[str, str]] = {}
        self._initialized = False
    
    def initialize_config(self, config: Any) -> None:
        """Record configuration info as metrics."""
        if not PROMETHEUS_AVAILABLE:
            return
        
        try:
            CONFIG_INFO.info({
                "extreme_fear_max": str(config.extreme_fear_max),
                "fear_max": str(config.fear_max),
                "greed_min": str(config.greed_min),
                "extreme_greed_min": str(config.extreme_greed_min),
                "vol_dead_max": str(config.vol_dead_max),
                "vol_low_max": str(config.vol_low_max),
                "vol_high_min": str(config.vol_high_min),
                "vol_extreme_min": str(config.vol_extreme_min),
                "sizing_floor": str(config.sizing_floor),
                "sizing_ceiling": str(config.sizing_ceiling),
                "contrarian_boost": str(config.contrarian_boost),
            })
            self._initialized = True
        except Exception as exc:
            logger.debug(f"Failed to record config metrics: {exc}")
    
    def record_sentiment(
        self,
        asset: str,
        sentiment: Any,
    ) -> None:
        """Record sentiment metrics."""
        if not PROMETHEUS_AVAILABLE or sentiment is None:
            return
        
        try:
            asset = asset.upper()
            
            # Record current values
            SENTIMENT_VALUE.labels(asset=asset).set(sentiment.value)
            SENTIMENT_CONFIDENCE.labels(asset=asset).set(sentiment.confidence)
            
            # Regime as numeric (0=extreme_fear, 1=fear, 2=neutral, 3=greed, 4=extreme_greed)
            regime_map = {
                "EXTREME_FEAR": 0,
                "FEAR": 1,
                "NEUTRAL": 2,
                "GREED": 3,
                "EXTREME_GREED": 4,
            }
            regime_num = regime_map.get(sentiment.regime.value, 2)
            SENTIMENT_REGIME.labels(asset=asset).set(regime_num)
            
            # Track distribution
            SENTIMENT_VALUE_DISTRIBUTION.labels(asset=asset).observe(sentiment.value)
            
            # Record data staleness
            if sentiment.timestamp:
                age = (datetime.now(timezone.utc) - sentiment.timestamp).total_seconds()
                DATA_STALENESS_SECONDS.labels(asset=asset, data_type="sentiment").set(age)
            
            # Track regime transitions
            self._track_regime_transition(asset, "sentiment", sentiment.regime.value)
            
        except Exception as exc:
            logger.debug(f"Failed to record sentiment metrics for {asset}: {exc}")
    
    def record_volatility(
        self,
        asset: str,
        volatility: Any,
    ) -> None:
        """Record volatility metrics."""
        if not PROMETHEUS_AVAILABLE or volatility is None:
            return
        
        try:
            asset = asset.upper()
            
            # Record current values
            VOLATILITY_VALUE.labels(asset=asset).set(volatility.value * 100)  # As percentage
            VOLATILITY_UNCERTAINTY.labels(asset=asset).set(volatility.uncertainty)
            
            # Regime as numeric (0=dead, 1=low, 2=target, 3=high, 4=extreme)
            regime_map = {
                "DEAD": 0,
                "LOW": 1,
                "TARGET": 2,
                "HIGH": 3,
                "EXTREME": 4,
            }
            regime_num = regime_map.get(volatility.regime.value, 2)
            VOLATILITY_REGIME.labels(asset=asset).set(regime_num)
            
            # Track distribution
            VOLATILITY_DISTRIBUTION.labels(asset=asset).observe(volatility.value)
            
            # Record data staleness
            if volatility.timestamp:
                age = (datetime.now(timezone.utc) - volatility.timestamp).total_seconds()
                DATA_STALENESS_SECONDS.labels(asset=asset, data_type="volatility").set(age)
            
            # Track regime transitions
            self._track_regime_transition(asset, "volatility", volatility.regime.value)
            
        except Exception as exc:
            logger.debug(f"Failed to record volatility metrics for {asset}: {exc}")
    
    def record_sizing_multiplier(
        self,
        asset: str,
        multiplier: Any,
        is_contrarian: bool = False,
    ) -> None:
        """Record sizing multiplier metrics."""
        if not PROMETHEUS_AVAILABLE or multiplier is None:
            return
        
        try:
            asset = asset.upper()
            contrarian_str = "true" if is_contrarian else "false"
            
            # Record current value
            SIZING_MULTIPLIER.labels(asset=asset, is_contrarian=contrarian_str).set(multiplier.value)
            
            # Regime label as numeric (0=NORMAL, 1=CAUTION, 2=HALTED)
            regime_map = {
                "NORMAL": 0,
                "CAUTION": 1,
                "HALTED": 2,
            }
            regime_num = regime_map.get(multiplier.get_regime_label(), 0)
            SIZING_REGIME_LABEL.labels(asset=asset).set(regime_num)
            
            # Track distribution
            SIZING_MULTIPLIER_DISTRIBUTION.labels(asset=asset).observe(multiplier.value)
            
            # Record alerts for extreme regimes
            if multiplier.value <= 0.3:
                ALERTS_FIRED.labels(
                    alert_type="extreme_sizing_reduction",
                    severity="high",
                    asset=asset
                ).inc()
            elif multiplier.value <= 0.5:
                ALERTS_FIRED.labels(
                    alert_type="significant_sizing_reduction",
                    severity="medium",
                    asset=asset
                ).inc()
            
        except Exception as exc:
            logger.debug(f"Failed to record sizing metrics for {asset}: {exc}")
    
    def record_service_health(
        self,
        health: Dict[str, Any],
    ) -> None:
        """Record service health metrics."""
        if not PROMETHEUS_AVAILABLE:
            return
        
        try:
            if health.get("running"):
                SERVICE_UPDATE_COUNT.labels(result="success").inc()
            
            error_count = health.get("error_count", 0)
            if error_count > 0:
                SERVICE_ERROR_COUNT.labels(error_type="generic").inc(error_count)
                
        except Exception as exc:
            logger.debug(f"Failed to record health metrics: {exc}")
    
    def _track_regime_transition(
        self,
        asset: str,
        regime_type: str,
        new_regime: str,
    ) -> None:
        """Track regime transitions."""
        if asset not in self._last_regimes:
            self._last_regimes[asset] = {}
        
        old_regime = self._last_regimes[asset].get(regime_type)
        
        if old_regime and old_regime != new_regime:
            REGIME_TRANSITIONS.labels(
                asset=asset,
                regime_type=regime_type,
                from_regime=old_regime,
                to_regime=new_regime,
            ).inc()
        
        self._last_regimes[asset][regime_type] = new_regime


# ═══════════════════════════════════════════════════════════════════════════
# Alert Rules Generator
# ═══════════════════════════════════════════════════════════════════════════

def generate_prometheus_alert_rules() -> Dict[str, Any]:
    """
    Generate Prometheus alert rules for sentiment/volatility/sizing.
    
    Returns alert rule definitions that can be written to a Prometheus
    rule file or loaded into Alertmanager.
    """
    return {
        "groups": [
            {
                "name": "sentiment_vol_alerts",
                "rules": [
                    {
                        "alert": "ExtremeFearDetected",
                        "expr": 'merid_sentiment_regime == 0',
                        "for": "1m",
                        "labels": {
                            "severity": "warning",
                            "category": "sentiment",
                        },
                        "annotations": {
                            "summary": "Extreme fear detected for {{ $labels.asset }}",
                            "description": "Fear/Greed Index indicates extreme fear (<=20) for {{ $labels.asset }}. Sizing multiplier will be reduced.",
                        },
                    },
                    {
                        "alert": "ExtremeGreedDetected",
                        "expr": 'merid_sentiment_regime == 4',
                        "for": "1m",
                        "labels": {
                            "severity": "warning",
                            "category": "sentiment",
                        },
                        "annotations": {
                            "summary": "Extreme greed detected for {{ $labels.asset }}",
                            "description": "Fear/Greed Index indicates extreme greed (>=80) for {{ $labels.asset }}. Sizing multiplier will be reduced.",
                        },
                    },
                    {
                        "alert": "ExtremeVolatilityDetected",
                        "expr": 'merid_volatility_regime == 4',
                        "for": "1m",
                        "labels": {
                            "severity": "critical",
                            "category": "volatility",
                        },
                        "annotations": {
                            "summary": "Extreme volatility detected for {{ $labels.asset }}",
                            "description": "Annualized volatility exceeds 120% for {{ $labels.asset }}. Position sizing severely reduced.",
                        },
                    },
                    {
                        "alert": "SizingMultiplierHalted",
                        "expr": 'merid_sizing_regime_label == 2',
                        "for": "30s",
                        "labels": {
                            "severity": "critical",
                            "category": "sizing",
                        },
                        "annotations": {
                            "summary": "Sizing halted for {{ $labels.asset }}",
                            "description": "Sizing multiplier is in HALTED regime (<=0.3) for {{ $labels.asset }}. New positions should not be taken.",
                        },
                    },
                    {
                        "alert": "SentimentDataStale",
                        "expr": 'merid_sentiment_vol_data_staleness_seconds{data_type="sentiment"} > 300',
                        "for": "2m",
                        "labels": {
                            "severity": "warning",
                            "category": "data_quality",
                        },
                        "annotations": {
                            "summary": "Sentiment data stale for {{ $labels.asset }}",
                            "description": "Sentiment data for {{ $labels.asset }} is more than 5 minutes old. Using fallback values.",
                        },
                    },
                    {
                        "alert": "VolatilityDataStale",
                        "expr": 'merid_sentiment_vol_data_staleness_seconds{data_type="volatility"} > 300',
                        "for": "2m",
                        "labels": {
                            "severity": "warning",
                            "category": "data_quality",
                        },
                        "annotations": {
                            "summary": "Volatility data stale for {{ $labels.asset }}",
                            "description": "Volatility data for {{ $labels.asset }} is more than 5 minutes old. Using fallback values.",
                        },
                    },
                    {
                        "alert": "SentimentVolServiceErrors",
                        "expr": 'rate(merid_sentiment_vol_service_errors_total[5m]) > 0.1',
                        "for": "2m",
                        "labels": {
                            "severity": "critical",
                            "category": "service_health",
                        },
                        "annotations": {
                            "summary": "Sentiment/Vol service experiencing errors",
                            "description": "Error rate for SentimentVolService is elevated (>0.1 errors/sec over 5m).",
                        },
                    },
                ],
            },
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════
# Grafana Dashboard Generator
# ═══════════════════════════════════════════════════════════════════════════

def generate_grafana_dashboard_json() -> Dict[str, Any]:
    """
    Generate Grafana dashboard JSON for Fear/Greed, Vol & Sizing.
    
    Returns a complete dashboard definition that can be imported into Grafana.
    """
    return {
        "dashboard": {
            "title": "Fear/Greed, Volatility & Sizing",
            "tags": ["sentiment", "volatility", "risk", "sizing"],
            "timezone": "utc",
            "refresh": "10s",
            "panels": [
                {
                    "id": 1,
                    "title": "Fear/Greed Index",
                    "type": "gauge",
                    "targets": [
                        {
                            "expr": 'merid_sentiment_value',
                            "legendFormat": "{{ asset }}",
                        },
                    ],
                    "fieldConfig": {
                        "min": 0,
                        "max": 100,
                        "thresholds": {
                            "steps": [
                                {"color": "red", "value": 0},
                                {"color": "orange", "value": 25},
                                {"color": "yellow", "value": 45},
                                {"color": "green", "value": 55},
                                {"color": "orange", "value": 75},
                                {"color": "red", "value": 80},
                            ],
                        },
                    },
                    "gridPos": {"h": 8, "w": 8, "x": 0, "y": 0},
                },
                {
                    "id": 2,
                    "title": "Annualized Volatility",
                    "type": "gauge",
                    "targets": [
                        {
                            "expr": 'merid_volatility_value',
                            "legendFormat": "{{ asset }}",
                        },
                    ],
                    "fieldConfig": {
                        "min": 0,
                        "max": 200,
                        "unit": "percent",
                        "thresholds": {
                            "steps": [
                                {"color": "blue", "value": 0},
                                {"color": "green", "value": 15},
                                {"color": "yellow", "value": 50},
                                {"color": "orange", "value": 70},
                                {"color": "red", "value": 120},
                            ],
                        },
                    },
                    "gridPos": {"h": 8, "w": 8, "x": 8, "y": 0},
                },
                {
                    "id": 3,
                    "title": "Sizing Multiplier",
                    "type": "gauge",
                    "targets": [
                        {
                            "expr": 'merid_sizing_multiplier{is_contrarian="false"}',
                            "legendFormat": "{{ asset }}",
                        },
                    ],
                    "fieldConfig": {
                        "min": 0,
                        "max": 1.2,
                        "thresholds": {
                            "steps": [
                                {"color": "red", "value": 0},
                                {"color": "orange", "value": 0.3},
                                {"color": "yellow", "value": 0.5},
                                {"color": "green", "value": 0.8},
                                {"color": "dark-green", "value": 1.0},
                            ],
                        },
                    },
                    "gridPos": {"h": 8, "w": 8, "x": 16, "y": 0},
                },
                {
                    "id": 4,
                    "title": "Sentiment History",
                    "type": "timeseries",
                    "targets": [
                        {
                            "expr": 'merid_sentiment_value',
                            "legendFormat": "{{ asset }}",
                        },
                    ],
                    "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
                },
                {
                    "id": 5,
                    "title": "Volatility History",
                    "type": "timeseries",
                    "targets": [
                        {
                            "expr": 'merid_volatility_value',
                            "legendFormat": "{{ asset }}",
                        },
                    ],
                    "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
                },
                {
                    "id": 6,
                    "title": "Regime Transitions",
                    "type": "stat",
                    "targets": [
                        {
                            "expr": 'rate(merid_regime_transitions_total[5m])',
                            "legendFormat": "{{ asset }} - {{ regime_type }}",
                        },
                    ],
                    "gridPos": {"h": 4, "w": 12, "x": 0, "y": 16},
                },
                {
                    "id": 7,
                    "title": "Alerts Fired",
                    "type": "stat",
                    "targets": [
                        {
                            "expr": 'rate(merid_sentiment_vol_alerts_fired_total[5m])',
                            "legendFormat": "{{ alert_type }}",
                        },
                    ],
                    "gridPos": {"h": 4, "w": 12, "x": 12, "y": 16},
                },
            ],
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# Singleton Accessor
# ═══════════════════════════════════════════════════════════════════════════

_metrics_recorder: Optional[SentimentVolMetricsRecorder] = None


def get_metrics_recorder() -> SentimentVolMetricsRecorder:
    """Get the singleton metrics recorder."""
    global _metrics_recorder
    if _metrics_recorder is None:
        _metrics_recorder = SentimentVolMetricsRecorder()
    return _metrics_recorder
