"""
Privacy-aware telemetry manager with data classification and retention tiers.

Handles structured logging, metrics, and traces with proper PII handling,
sampling, and multi-tier storage for cost control and compliance.
"""

import logging
import hashlib
import json
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import uuid

logger = logging.getLogger(__name__)


class DataClassification(Enum):
    """Data sensitivity classification."""
    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    SECRET = "secret"


class RetentionTier(Enum):
    """Storage retention tier."""
    HOT = "hot"          # 7-30 days, full fidelity
    WARM = "warm"        # 3-12 months, downsampled
    COLD = "cold"        # 1-7 years, aggregated/compressed
    ARCHIVE = "archive"  # Long-term compliance, minimal


@dataclass
class TelemetryConfig:
    """Configuration for telemetry stream."""
    stream_name: str
    classification: DataClassification
    retention_tier: RetentionTier
    sampling_rate: float = 1.0
    pii_fields: Set[str] = field(default_factory=set)
    mask_fields: Set[str] = field(default_factory=set)
    retention_days: int = 30
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StructuredLog:
    """Structured log entry."""
    timestamp: datetime
    level: str
    agent_id: Optional[str]
    strategy_id: Optional[str]
    venue: Optional[str]
    correlation_id: str
    trace_id: str
    event_type: str
    message: str
    fields: Dict[str, Any]
    classification: DataClassification
    regime_tags: List[str] = field(default_factory=list)


@dataclass
class MetricPoint:
    """Time-series metric point."""
    timestamp: datetime
    metric_name: str
    value: float
    tags: Dict[str, str]
    classification: DataClassification
    unit: Optional[str] = None


@dataclass
class TraceSpan:
    """Distributed trace span."""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    operation_name: str
    start_time: datetime
    end_time: Optional[datetime]
    duration_ms: Optional[float]
    tags: Dict[str, Any]
    logs: List[Dict[str, Any]]
    classification: DataClassification


class TelemetryManager:
    """
    Manage privacy-aware telemetry with classification and retention.
    
    Capabilities:
    - Data classification (public/internal/sensitive/secret)
    - PII masking and pseudonymization
    - Adaptive sampling by stream
    - Multi-tier retention (hot/warm/cold/archive)
    - Structured logging with correlation IDs
    - Metrics and distributed tracing
    """
    
    def __init__(self):
        self._configs: Dict[str, TelemetryConfig] = {}
        self._logs: List[StructuredLog] = []
        self._metrics: List[MetricPoint] = []
        self._traces: Dict[str, List[TraceSpan]] = {}
        self._pii_mapping: Dict[str, str] = {}
        
        # Forbidden keys that must never be logged
        self._forbidden_keys = {
            "private_key",
            "secret_key",
            "api_key",
            "password",
            "seed_phrase",
            "mnemonic",
            "jwt_token",
            "access_token",
            "refresh_token",
        }
    
    def register_stream(self, config: TelemetryConfig) -> None:
        """Register a telemetry stream with configuration."""
        self._configs[config.stream_name] = config
        logger.info(
            f"Registered telemetry stream '{config.stream_name}': "
            f"classification={config.classification.value}, "
            f"tier={config.retention_tier.value}, "
            f"sampling={config.sampling_rate}"
        )
    
    def _should_sample(self, stream_name: str) -> bool:
        """Determine if event should be sampled."""
        config = self._configs.get(stream_name)
        if not config:
            return True
        
        import random
        return random.random() < config.sampling_rate
    
    def _mask_pii(self, data: Dict[str, Any], config: TelemetryConfig) -> Dict[str, Any]:
        """Mask PII fields in data."""
        masked = data.copy()
        
        for field in config.mask_fields:
            if field in masked:
                if isinstance(masked[field], str):
                    masked[field] = self._pseudonymize(masked[field])
                else:
                    masked[field] = "***MASKED***"
        
        return masked
    
    def _pseudonymize(self, value: str) -> str:
        """Create pseudonymous ID for PII value."""
        if value in self._pii_mapping:
            return self._pii_mapping[value]
        
        # Create deterministic hash
        pseudo_id = hashlib.sha256(value.encode()).hexdigest()[:16]
        self._pii_mapping[value] = pseudo_id
        
        return pseudo_id
    
    def _check_forbidden_keys(self, data: Dict[str, Any]) -> None:
        """Raise error if forbidden keys are present."""
        for key in data.keys():
            if key.lower() in self._forbidden_keys:
                raise ValueError(
                    f"Forbidden key '{key}' detected in telemetry. "
                    f"Never log secrets or credentials."
                )
    
    def log_structured(
        self,
        stream_name: str,
        level: str,
        event_type: str,
        message: str,
        fields: Dict[str, Any],
        agent_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        venue: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        regime_tags: Optional[List[str]] = None,
    ) -> Optional[StructuredLog]:
        """
        Log structured event with classification and PII handling.
        
        Args:
            stream_name: Telemetry stream name
            level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            event_type: Type of event
            message: Human-readable message
            fields: Structured fields
            agent_id: Optional agent ID
            strategy_id: Optional strategy ID
            venue: Optional venue
            correlation_id: Optional correlation ID
            trace_id: Optional trace ID
            regime_tags: Optional regime tags
            
        Returns:
            StructuredLog if sampled, None otherwise
        """
        # Check for forbidden keys
        self._check_forbidden_keys(fields)
        
        # Check sampling
        if not self._should_sample(stream_name):
            return None
        
        config = self._configs.get(stream_name)
        if not config:
            raise ValueError(f"Stream '{stream_name}' not registered")
        
        # Mask PII
        masked_fields = self._mask_pii(fields, config)
        
        # Generate IDs if not provided
        if correlation_id is None:
            correlation_id = str(uuid.uuid4())
        if trace_id is None:
            trace_id = str(uuid.uuid4())
        
        log_entry = StructuredLog(
            timestamp=datetime.utcnow(),
            level=level,
            agent_id=agent_id,
            strategy_id=strategy_id,
            venue=venue,
            correlation_id=correlation_id,
            trace_id=trace_id,
            event_type=event_type,
            message=message,
            fields=masked_fields,
            classification=config.classification,
            regime_tags=regime_tags or [],
        )
        
        self._logs.append(log_entry)
        
        # Also log to standard logger
        logger.log(
            getattr(logging, level),
            f"[{event_type}] {message}",
            extra={
                "agent_id": agent_id,
                "correlation_id": correlation_id,
                "trace_id": trace_id,
                **masked_fields,
            },
        )
        
        return log_entry
    
    def record_metric(
        self,
        stream_name: str,
        metric_name: str,
        value: float,
        tags: Optional[Dict[str, str]] = None,
        unit: Optional[str] = None,
    ) -> Optional[MetricPoint]:
        """
        Record a metric point.
        
        Args:
            stream_name: Telemetry stream name
            metric_name: Metric name
            value: Metric value
            tags: Optional tags
            unit: Optional unit
            
        Returns:
            MetricPoint if sampled, None otherwise
        """
        if not self._should_sample(stream_name):
            return None
        
        config = self._configs.get(stream_name)
        if not config:
            raise ValueError(f"Stream '{stream_name}' not registered")
        
        metric = MetricPoint(
            timestamp=datetime.utcnow(),
            metric_name=metric_name,
            value=value,
            tags=tags or {},
            classification=config.classification,
            unit=unit,
        )
        
        self._metrics.append(metric)
        
        return metric
    
    def start_trace_span(
        self,
        stream_name: str,
        operation_name: str,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        tags: Optional[Dict[str, Any]] = None,
    ) -> TraceSpan:
        """
        Start a distributed trace span.
        
        Args:
            stream_name: Telemetry stream name
            operation_name: Operation name
            trace_id: Optional trace ID (generated if not provided)
            parent_span_id: Optional parent span ID
            tags: Optional tags
            
        Returns:
            TraceSpan
        """
        config = self._configs.get(stream_name)
        if not config:
            raise ValueError(f"Stream '{stream_name}' not registered")
        
        if trace_id is None:
            trace_id = str(uuid.uuid4())
        
        span = TraceSpan(
            trace_id=trace_id,
            span_id=str(uuid.uuid4()),
            parent_span_id=parent_span_id,
            operation_name=operation_name,
            start_time=datetime.utcnow(),
            end_time=None,
            duration_ms=None,
            tags=tags or {},
            logs=[],
            classification=config.classification,
        )
        
        if trace_id not in self._traces:
            self._traces[trace_id] = []
        self._traces[trace_id].append(span)
        
        return span
    
    def end_trace_span(self, span: TraceSpan) -> None:
        """End a trace span and compute duration."""
        span.end_time = datetime.utcnow()
        span.duration_ms = (span.end_time - span.start_time).total_seconds() * 1000
    
    def add_span_log(self, span: TraceSpan, log: Dict[str, Any]) -> None:
        """Add log entry to span."""
        span.logs.append({
            "timestamp": datetime.utcnow().isoformat(),
            **log,
        })
    
    def get_logs(
        self,
        stream_name: Optional[str] = None,
        level: Optional[str] = None,
        agent_id: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[StructuredLog]:
        """Query logs with filters."""
        logs = self._logs
        
        if stream_name:
            logs = [
                log for log in logs
                if log.event_type.startswith(stream_name)
            ]
        
        if level:
            logs = [log for log in logs if log.level == level]
        
        if agent_id:
            logs = [log for log in logs if log.agent_id == agent_id]
        
        if since:
            logs = [log for log in logs if log.timestamp >= since]
        
        return logs[-limit:]
    
    def get_metrics(
        self,
        metric_name: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        since: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[MetricPoint]:
        """Query metrics with filters."""
        metrics = self._metrics
        
        if metric_name:
            metrics = [m for m in metrics if m.metric_name == metric_name]
        
        if tags:
            metrics = [
                m for m in metrics
                if all(m.tags.get(k) == v for k, v in tags.items())
            ]
        
        if since:
            metrics = [m for m in metrics if m.timestamp >= since]
        
        return metrics[-limit:]
    
    def get_trace(self, trace_id: str) -> List[TraceSpan]:
        """Get all spans for a trace."""
        return self._traces.get(trace_id, [])
    
    def get_telemetry_stats(self) -> Dict[str, Any]:
        """Get telemetry statistics."""
        stats = {
            "total_logs": len(self._logs),
            "total_metrics": len(self._metrics),
            "total_traces": len(self._traces),
            "streams": {},
        }
        
        for name, config in self._configs.items():
            stream_logs = [
                log for log in self._logs
                if log.event_type.startswith(name)
            ]
            
            stream_metrics = [
                m for m in self._metrics
                if m.metric_name.startswith(name)
            ]
            
            stats["streams"][name] = {
                "classification": config.classification.value,
                "retention_tier": config.retention_tier.value,
                "sampling_rate": config.sampling_rate,
                "log_count": len(stream_logs),
                "metric_count": len(stream_metrics),
                "retention_days": config.retention_days,
            }
        
        return stats
    
    def cleanup_expired(self) -> Dict[str, int]:
        """Remove expired telemetry based on retention policies."""
        now = datetime.utcnow()
        removed = {"logs": 0, "metrics": 0, "traces": 0}
        
        # Clean logs
        original_log_count = len(self._logs)
        self._logs = [
            log for log in self._logs
            if self._is_within_retention(log.timestamp, log.event_type)
        ]
        removed["logs"] = original_log_count - len(self._logs)
        
        # Clean metrics
        original_metric_count = len(self._metrics)
        self._metrics = [
            m for m in self._metrics
            if self._is_within_retention(m.timestamp, m.metric_name)
        ]
        removed["metrics"] = original_metric_count - len(self._metrics)
        
        # Clean traces
        original_trace_count = len(self._traces)
        for trace_id in list(self._traces.keys()):
            spans = self._traces[trace_id]
            if spans and not self._is_within_retention(
                spans[0].start_time,
                spans[0].operation_name,
            ):
                del self._traces[trace_id]
        removed["traces"] = original_trace_count - len(self._traces)
        
        if sum(removed.values()) > 0:
            logger.info(f"Cleaned up expired telemetry: {removed}")
        
        return removed
    
    def _is_within_retention(self, timestamp: datetime, stream_name: str) -> bool:
        """Check if timestamp is within retention period."""
        config = self._configs.get(stream_name)
        if not config:
            return True
        
        age = datetime.utcnow() - timestamp
        return age.days <= config.retention_days


# Global singleton
_telemetry_manager: Optional[TelemetryManager] = None


def get_telemetry_manager() -> TelemetryManager:
    """Get global TelemetryManager instance."""
    global _telemetry_manager
    if _telemetry_manager is None:
        _telemetry_manager = TelemetryManager()
        _initialize_default_streams()
    return _telemetry_manager


def _initialize_default_streams() -> None:
    """Initialize default telemetry streams."""
    tm = get_telemetry_manager()
    
    # Critical streams - full sampling, hot storage
    tm.register_stream(TelemetryConfig(
        stream_name="execution",
        classification=DataClassification.SENSITIVE,
        retention_tier=RetentionTier.HOT,
        sampling_rate=1.0,
        retention_days=30,
        pii_fields={"user_id"},
        mask_fields={"user_id"},
    ))
    
    tm.register_stream(TelemetryConfig(
        stream_name="risk",
        classification=DataClassification.SENSITIVE,
        retention_tier=RetentionTier.HOT,
        sampling_rate=1.0,
        retention_days=30,
    ))
    
    tm.register_stream(TelemetryConfig(
        stream_name="governance",
        classification=DataClassification.INTERNAL,
        retention_tier=RetentionTier.WARM,
        sampling_rate=1.0,
        retention_days=365,
    ))

    tm.register_stream(TelemetryConfig(
        stream_name="meta_audit",
        classification=DataClassification.INTERNAL,
        retention_tier=RetentionTier.WARM,
        sampling_rate=1.0,
        retention_days=365,
        metadata={"owner": "meta_audit_runtime"},
    ))

    tm.register_stream(TelemetryConfig(
        stream_name="test_swarm",
        classification=DataClassification.INTERNAL,
        retention_tier=RetentionTier.WARM,
        sampling_rate=1.0,
        retention_days=365,
        metadata={"owner": "test_swarm"},
    ))

    tm.register_stream(TelemetryConfig(
        stream_name="gamification",
        classification=DataClassification.INTERNAL,
        retention_tier=RetentionTier.WARM,
        sampling_rate=1.0,
        retention_days=365,
        metadata={"owner": "gamification_swarm"},
    ))
    
    # High-volume streams - sampled, warm storage
    tm.register_stream(TelemetryConfig(
        stream_name="strategy",
        classification=DataClassification.INTERNAL,
        retention_tier=RetentionTier.WARM,
        sampling_rate=0.1,
        retention_days=90,
    ))
    
    tm.register_stream(TelemetryConfig(
        stream_name="market_data",
        classification=DataClassification.PUBLIC,
        retention_tier=RetentionTier.WARM,
        sampling_rate=0.01,
        retention_days=90,
    ))
    
    # Analytics streams - cold storage
    tm.register_stream(TelemetryConfig(
        stream_name="analytics",
        classification=DataClassification.INTERNAL,
        retention_tier=RetentionTier.COLD,
        sampling_rate=1.0,
        retention_days=730,
    ))

    # Social coordination stream - swarm lab + social bot health heartbeats
    tm.register_stream(TelemetryConfig(
        stream_name="social",
        classification=DataClassification.INTERNAL,
        retention_tier=RetentionTier.WARM,
        sampling_rate=1.0,
        retention_days=180,
    ))
