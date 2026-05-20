"""
Observability and Tracing for 15m Pipeline Execution

Provides structured logging, tracing, and health monitoring for the 15m execution shell.
"""

from __future__ import annotations

import uuid
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime
from functools import wraps

from merid.pipelines.feature_bundle import (
    FifteenMinuteFeatureBundle,
    TradeDecision,
)
from utils.logger import get_logger

logger = get_logger("merid.pipelines.observability")


@dataclass
class FeatureNamespaceSummary:
    """Summary of features from a specific namespace."""
    namespace: str
    feature_count: int
    mean_value: float = 0.0
    std_value: float = 0.0
    missing_count: int = 0
    source_agents: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "namespace": self.namespace,
            "feature_count": self.feature_count,
            "mean_value": self.mean_value,
            "std_value": self.std_value,
            "missing_count": self.missing_count,
            "source_agents": self.source_agents,
        }


@dataclass
class DecisionTrace:
    """Complete trace of a 15m decision lifecycle."""
    trace_id: str
    asset: str
    timeframe: str
    pipeline_id: str
    timestamp: datetime
    
    # Feature bundle snapshot
    feature_summaries: Dict[str, FeatureNamespaceSummary] = field(default_factory=dict)
    feature_time_window: tuple[Optional[datetime], Optional[datetime]] = (None, None)
    features_fingerprint: str = ""
    
    # Decision output
    decision: Optional[TradeDecision] = None
    
    # Risk check results
    risk_checks: List[Dict[str, Any]] = field(default_factory=list)
    risk_passed: bool = False
    
    # Execution result
    execution_success: bool = False
    execution_error: str = ""
    
    # Timing
    feature_build_ms: float = 0.0
    decision_ms: float = 0.0
    risk_check_ms: float = 0.0
    execution_ms: float = 0.0
    total_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "trace_id": self.trace_id,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "pipeline_id": self.pipeline_id,
            "timestamp": self.timestamp.isoformat(),
            "feature_summaries": {
                ns: summary.to_dict()
                for ns, summary in self.feature_summaries.items()
            },
            "feature_time_window": [
                self.feature_time_window[0].isoformat() if self.feature_time_window[0] else None,
                self.feature_time_window[1].isoformat() if self.feature_time_window[1] else None,
            ],
            "features_fingerprint": self.features_fingerprint,
            "decision": self.decision.to_dict() if self.decision else None,
            "risk_checks": self.risk_checks,
            "risk_passed": self.risk_passed,
            "execution_success": self.execution_success,
            "execution_error": self.execution_error,
            "timing": {
                "feature_build_ms": self.feature_build_ms,
                "decision_ms": self.decision_ms,
                "risk_check_ms": self.risk_check_ms,
                "execution_ms": self.execution_ms,
                "total_ms": self.total_ms,
            },
        }


class PipelineObservability:
    """
    Observability wrapper for 15m pipeline execution.
    
    Provides:
    - Trace ID generation and propagation
    - Feature namespace summarization
    - Decision lifecycle tracing
    - Structured logging
    """
    
    def __init__(self):
        self.traces: Dict[str, DecisionTrace] = {}
        self.health_metrics: Dict[str, Any] = {
            "feature_sparsity": {},
            "feature_drift": {},
            "agent_failure_rates": {},
        }
    
    def generate_trace_id(self) -> str:
        """Generate a unique trace ID."""
        return str(uuid.uuid4())
    
    def compute_feature_fingerprint(
        self,
        bundle: FifteenMinuteFeatureBundle,
    ) -> str:
        """
        Compute a hash fingerprint of the feature bundle for auditability.
        
        Args:
            bundle: Feature bundle to fingerprint
            
        Returns:
            SHA256 hash of feature bundle
        """
        # Serialize bundle to string
        bundle_dict = bundle.to_dict()
        bundle_str = str(sorted(bundle_dict.items()))
        
        # Compute hash
        return hashlib.sha256(bundle_str.encode()).hexdigest()[:16]
    
    def summarize_namespace(
        self,
        bundle: FifteenMinuteFeatureBundle,
        namespace: str,
    ) -> FeatureNamespaceSummary:
        """
        Summarize features from a specific namespace.
        
        Args:
            bundle: Feature bundle
            namespace: Namespace to summarize
            
        Returns:
            FeatureNamespaceSummary with statistics
        """
        namespace_map = {
            "ts_15m": bundle.ts_15m,
            "ts_lower_tf": bundle.ts_lower_tf,
            "ts_higher_tf": bundle.ts_higher_tf,
            "sentiment": bundle.sentiment,
            "macro": bundle.macro,
            "confidence_signals": bundle.confidence_signals,
            "volatility": bundle.volatility,
        }
        
        fd = namespace_map.get(namespace)
        if not fd:
            return FeatureNamespaceSummary(
                namespace=namespace,
                feature_count=0,
                missing_count=0,
            )
        
        features = fd.features
        if not features:
            return FeatureNamespaceSummary(
                namespace=namespace,
                feature_count=0,
                missing_count=0,
            )
        
        # Compute statistics
        values = list(features.values())
        mean_val = sum(values) / len(values) if values else 0.0
        std_val = (
            (sum((x - mean_val) ** 2 for x in values) / len(values)) ** 0.5
            if len(values) > 1
            else 0.0
        )
        
        # Count missing (zero or None)
        missing_count = sum(1 for v in values if v == 0.0 or v is None)
        
        return FeatureNamespaceSummary(
            namespace=namespace,
            feature_count=len(features),
            mean_value=mean_val,
            std_value=std_val,
            missing_count=missing_count,
            source_agents=[fd.source_agent] if fd.source_agent else [],
        )
    
    def start_trace(
        self,
        asset: str,
        timeframe: str,
        pipeline_id: str,
    ) -> DecisionTrace:
        """Start a new decision trace."""
        trace_id = self.generate_trace_id()
        trace = DecisionTrace(
            trace_id=trace_id,
            asset=asset,
            timeframe=timeframe,
            pipeline_id=pipeline_id,
            timestamp=datetime.utcnow(),
        )
        self.traces[trace_id] = trace
        return trace
    
    def log_feature_bundle(
        self,
        trace: DecisionTrace,
        bundle: FifteenMinuteFeatureBundle,
    ) -> None:
        """Log feature bundle snapshot to trace."""
        # Compute fingerprint
        trace.features_fingerprint = self.compute_feature_fingerprint(bundle)
        
        # Capture time window
        trace.feature_time_window = (
            bundle.timestamp,
            datetime.utcnow(),
        )
        
        # Summarize each namespace
        namespaces = [
            "ts_15m",
            "ts_lower_tf",
            "ts_higher_tf",
            "sentiment",
            "macro",
            "confidence_signals",
            "volatility",
        ]
        
        for namespace in namespaces:
            summary = self.summarize_namespace(bundle, namespace)
            trace.feature_summaries[namespace] = summary
        
        # Update health metrics (sparsity)
        for namespace, summary in trace.feature_summaries.items():
            total_features = summary.feature_count + summary.missing_count
            if total_features > 0:
                sparsity = summary.missing_count / total_features
                if namespace not in self.health_metrics["feature_sparsity"]:
                    self.health_metrics["feature_sparsity"][namespace] = []
                self.health_metrics["feature_sparsity"][namespace].append(sparsity)
    
    def log_decision(
        self,
        trace: DecisionTrace,
        decision: TradeDecision,
    ) -> None:
        """Log decision output to trace."""
        trace.decision = decision
        trace.decision.trace_id = trace.trace_id  # Propagate trace ID
    
    def log_risk_checks(
        self,
        trace: DecisionTrace,
        risk_results: List[Any],
        risk_passed: bool,
    ) -> None:
        """Log risk check results to trace."""
        trace.risk_checks = [
            {
                "check_name": r.check_name,
                "passed": r.passed,
                "reason": r.reason,
                "adjusted_size_pct": r.adjusted_size_pct,
            }
            for r in risk_results
        ]
        trace.risk_passed = risk_passed
    
    def log_execution(
        self,
        trace: DecisionTrace,
        success: bool,
        error: str = "",
    ) -> None:
        """Log execution result to trace."""
        trace.execution_success = success
        trace.execution_error = error
        trace.total_ms = (
            trace.feature_build_ms +
            trace.decision_ms +
            trace.risk_check_ms +
            trace.execution_ms
        )
    
    def finalize_trace(self, trace: DecisionTrace) -> None:
        """Finalize and log the complete trace."""
        # Calculate total timing
        trace.total_ms = (
            trace.feature_build_ms +
            trace.decision_ms +
            trace.risk_check_ms +
            trace.execution_ms
        )
        
        logger.info(
            f"Decision trace completed: {trace.trace_id} | "
            f"asset={trace.asset} | "
            f"decision={'YES' if trace.decision and trace.decision.side == 'yes' else 'NO' if trace.decision else 'NONE'} | "
            f"risk_passed={trace.risk_passed} | "
            f"execution_success={trace.execution_success} | "
            f"total_ms={trace.total_ms:.1f}"
        )
        
        # Log to file for audit trail
        trace_dict = trace.to_dict()
        logger.debug(f"Full trace: {trace_dict}")
    
    def get_health_summary(self) -> Dict[str, Any]:
        """Get summary of health metrics."""
        summary = {
            "total_traces": len(self.traces),
            "feature_sparsity": {},
        }
        
        # Compute average sparsity per namespace
        for namespace, sparsity_list in self.health_metrics["feature_sparsity"].items():
            if sparsity_list:
                summary["feature_sparsity"][namespace] = {
                    "avg_sparsity": sum(sparsity_list) / len(sparsity_list),
                    "sample_count": len(sparsity_list),
                }
        
        return summary


def traced_pipeline_run(func):
    """
    Decorator to add tracing to pipeline run methods.
    
    Automatically generates trace ID, logs feature bundle,
    decision, risk checks, and execution.
    """
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        # Extract parameters
        pipeline_id = kwargs.get("pipeline_id") or args[0]
        context = kwargs.get("context") or args[1]
        
        # Get pipeline config
        pipeline = self.pipeline_registry.get_pipeline(pipeline_id)
        if not pipeline:
            return await func(self, *args, **kwargs)
        
        # Start trace
        trace = self.observability.start_trace(
            asset=pipeline.asset,
            timeframe=pipeline.timeframe,
            pipeline_id=pipeline_id,
        )
        
        try:
            # Run original function
            import time
            start_time = time.time()
            
            result = await func(self, *args, **kwargs)
            
            # If result is a TradeDecision, log it
            if isinstance(result, TradeDecision):
                self.observability.log_decision(trace, result)
                trace.decision_ms = (time.time() - start_time) * 1000
            
            return result
        
        except Exception as e:
            logger.error(f"Pipeline run error: {e}")
            trace.execution_success = False
            trace.execution_error = str(e)
            raise
        
        finally:
            self.observability.finalize_trace(trace)
    
    return wrapper
