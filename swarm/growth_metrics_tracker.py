"""
Growth and evolution metrics tracking for exponential scaling.

Tracks scaling-law metrics, evolution metrics, and swarm health to measure
whether the system is actually improving and scaling over time.
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict, deque
from enum import Enum
import numpy as np
import json
from pathlib import Path

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """Type of growth metric."""
    SCALING_LAW = "scaling_law"
    EVOLUTION = "evolution"
    SWARM_HEALTH = "swarm_health"
    FRONTIER = "frontier"


@dataclass
class ScalingLawMetric:
    """Scaling law metric tracking performance vs complexity."""
    metric_id: str
    name: str
    x_axis: str
    y_axis: str
    data_points: List[Tuple[float, float]] = field(default_factory=list)
    diminishing_returns_threshold: Optional[float] = None
    last_updated: Optional[datetime] = None


@dataclass
class EvolutionMetric:
    """Evolution metric tracking system improvement over time."""
    metric_id: str
    name: str
    description: str
    current_value: float
    history: List[Tuple[datetime, float]] = field(default_factory=list)
    target_value: Optional[float] = None
    trend: str = "stable"


@dataclass
class SwarmHealthMetric:
    """Swarm health metric for system reliability."""
    metric_id: str
    name: str
    current_value: float
    threshold: float
    healthy: bool
    history: List[Tuple[datetime, float]] = field(default_factory=list)


@dataclass
class ParetoPoint:
    """Point on Pareto frontier."""
    point_id: str
    timestamp: datetime
    strategy_id: str
    agent_id: str
    dimensions: Dict[str, float]
    dominated: bool = False


@dataclass
class InnovationRecord:
    """Record of innovation (new strategy/agent)."""
    innovation_id: str
    timestamp: datetime
    innovation_type: str
    name: str
    proposed_by: str
    tested: bool = False
    promoted: bool = False
    success_metrics: Dict[str, float] = field(default_factory=dict)


class GrowthMetricsTracker:
    """
    Growth and evolution metrics tracker.
    
    Tracks:
    - Scaling-law metrics (performance vs agents/tools/models/data)
    - Evolution metrics (innovation rate, frontier shift, reusability)
    - Swarm health metrics (reliability, drift, human intervention)
    - Pareto frontier for multi-objective optimization
    """
    
    def __init__(self, metrics_file: str = "swarm/growth_metrics.json"):
        self.metrics_file = Path(metrics_file)
        self.metrics_file.parent.mkdir(parents=True, exist_ok=True)
        
        self._scaling_law_metrics: Dict[str, ScalingLawMetric] = {}
        self._evolution_metrics: Dict[str, EvolutionMetric] = {}
        self._swarm_health_metrics: Dict[str, SwarmHealthMetric] = {}
        self._pareto_frontier: List[ParetoPoint] = []
        self._innovations: List[InnovationRecord] = []
        
        self._initialize_metrics()
        self._load_metrics()
    
    def _initialize_metrics(self) -> None:
        """Initialize standard growth metrics."""
        # Scaling law metrics
        self.register_scaling_law_metric(
            metric_id="performance_vs_agents",
            name="Performance vs Number of Agents",
            x_axis="num_agents",
            y_axis="sharpe_ratio",
            diminishing_returns_threshold=0.1,
        )
        
        self.register_scaling_law_metric(
            metric_id="performance_vs_tools",
            name="Performance vs Number of Tools",
            x_axis="num_tools",
            y_axis="sharpe_ratio",
            diminishing_returns_threshold=0.05,
        )
        
        self.register_scaling_law_metric(
            metric_id="performance_vs_data",
            name="Performance vs Data Volume",
            x_axis="data_volume_gb",
            y_axis="sharpe_ratio",
            diminishing_returns_threshold=0.02,
        )
        
        self.register_scaling_law_metric(
            metric_id="performance_vs_model_size",
            name="Performance vs Model Parameters",
            x_axis="model_params_millions",
            y_axis="sharpe_ratio",
            diminishing_returns_threshold=0.03,
        )
        
        # Evolution metrics
        self.register_evolution_metric(
            metric_id="innovation_rate",
            name="Innovation Rate",
            description="New strategies/agents proposed per week",
            current_value=0.0,
            target_value=5.0,
        )
        
        self.register_evolution_metric(
            metric_id="promotion_rate",
            name="Promotion Rate",
            description="Fraction of tested innovations successfully promoted",
            current_value=0.0,
            target_value=0.3,
        )
        
        self.register_evolution_metric(
            metric_id="reusability_rate",
            name="Reusability Rate",
            description="Fraction of innovations reusing existing patterns",
            current_value=0.0,
            target_value=0.7,
        )
        
        self.register_evolution_metric(
            metric_id="frontier_shift",
            name="Frontier Shift",
            description="Movement of Pareto frontier per month",
            current_value=0.0,
            target_value=0.1,
        )
        
        # Swarm health metrics
        self.register_swarm_health_metric(
            metric_id="avg_agent_reliability",
            name="Average Agent Reliability",
            current_value=0.0,
            threshold=0.8,
        )
        
        self.register_swarm_health_metric(
            metric_id="drift_resolution_time",
            name="Drift Resolution Time (hours)",
            current_value=0.0,
            threshold=24.0,
        )
        
        self.register_swarm_health_metric(
            metric_id="human_intervention_rate",
            name="Human Intervention Rate (per day)",
            current_value=0.0,
            threshold=5.0,
        )
        
        logger.info("Initialized growth and evolution metrics")
    
    def register_scaling_law_metric(
        self,
        metric_id: str,
        name: str,
        x_axis: str,
        y_axis: str,
        diminishing_returns_threshold: Optional[float] = None,
    ) -> ScalingLawMetric:
        """Register a scaling law metric."""
        metric = ScalingLawMetric(
            metric_id=metric_id,
            name=name,
            x_axis=x_axis,
            y_axis=y_axis,
            diminishing_returns_threshold=diminishing_returns_threshold,
        )
        
        self._scaling_law_metrics[metric_id] = metric
        
        logger.info(f"Registered scaling law metric '{metric_id}': {name}")
        
        return metric
    
    def register_evolution_metric(
        self,
        metric_id: str,
        name: str,
        description: str,
        current_value: float,
        target_value: Optional[float] = None,
    ) -> EvolutionMetric:
        """Register an evolution metric."""
        metric = EvolutionMetric(
            metric_id=metric_id,
            name=name,
            description=description,
            current_value=current_value,
            target_value=target_value,
        )
        
        self._evolution_metrics[metric_id] = metric
        
        logger.info(f"Registered evolution metric '{metric_id}': {name}")
        
        return metric
    
    def register_swarm_health_metric(
        self,
        metric_id: str,
        name: str,
        current_value: float,
        threshold: float,
    ) -> SwarmHealthMetric:
        """Register a swarm health metric."""
        metric = SwarmHealthMetric(
            metric_id=metric_id,
            name=name,
            current_value=current_value,
            threshold=threshold,
            healthy=current_value >= threshold if "rate" not in metric_id else current_value <= threshold,
        )
        
        self._swarm_health_metrics[metric_id] = metric
        
        logger.info(f"Registered swarm health metric '{metric_id}': {name}")
        
        return metric
    
    def record_scaling_law_point(
        self,
        metric_id: str,
        x_value: float,
        y_value: float,
    ) -> None:
        """Record a data point for scaling law metric."""
        if metric_id not in self._scaling_law_metrics:
            raise ValueError(f"Scaling law metric '{metric_id}' not found")
        
        metric = self._scaling_law_metrics[metric_id]
        metric.data_points.append((x_value, y_value))
        metric.last_updated = datetime.utcnow()
        
        # Check for diminishing returns
        if metric.diminishing_returns_threshold and len(metric.data_points) >= 3:
            recent_points = sorted(metric.data_points[-3:], key=lambda p: p[0])
            
            # Compute marginal improvement
            x1, y1 = recent_points[-2]
            x2, y2 = recent_points[-1]
            
            if x2 > x1:
                marginal_improvement = (y2 - y1) / (x2 - x1)
                
                if marginal_improvement < metric.diminishing_returns_threshold:
                    logger.warning(
                        f"Diminishing returns detected for '{metric_id}': "
                        f"marginal improvement {marginal_improvement:.4f} < "
                        f"threshold {metric.diminishing_returns_threshold}"
                    )
        
        self._save_metrics()
    
    def update_evolution_metric(
        self,
        metric_id: str,
        new_value: float,
    ) -> None:
        """Update evolution metric value."""
        if metric_id not in self._evolution_metrics:
            raise ValueError(f"Evolution metric '{metric_id}' not found")
        
        metric = self._evolution_metrics[metric_id]
        metric.history.append((datetime.utcnow(), new_value))
        metric.current_value = new_value
        
        # Compute trend
        if len(metric.history) >= 3:
            recent_values = [v for _, v in metric.history[-3:]]
            if recent_values[-1] > recent_values[0]:
                metric.trend = "improving"
            elif recent_values[-1] < recent_values[0]:
                metric.trend = "declining"
            else:
                metric.trend = "stable"
        
        self._save_metrics()
    
    def update_swarm_health_metric(
        self,
        metric_id: str,
        new_value: float,
    ) -> None:
        """Update swarm health metric value."""
        if metric_id not in self._swarm_health_metrics:
            raise ValueError(f"Swarm health metric '{metric_id}' not found")
        
        metric = self._swarm_health_metrics[metric_id]
        metric.history.append((datetime.utcnow(), new_value))
        metric.current_value = new_value
        
        # Update health status
        if "rate" in metric_id or "time" in metric_id:
            # Lower is better
            metric.healthy = new_value <= metric.threshold
        else:
            # Higher is better
            metric.healthy = new_value >= metric.threshold
        
        self._save_metrics()
    
    def record_innovation(
        self,
        innovation_type: str,
        name: str,
        proposed_by: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> InnovationRecord:
        """Record a new innovation (strategy/agent/tool)."""
        import hashlib
        innovation_id = hashlib.md5(
            f"{innovation_type}_{name}_{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        innovation = InnovationRecord(
            innovation_id=innovation_id,
            timestamp=datetime.utcnow(),
            innovation_type=innovation_type,
            name=name,
            proposed_by=proposed_by,
        )
        
        self._innovations.append(innovation)
        
        # Update innovation rate
        self._update_innovation_rate()
        
        logger.info(
            f"Recorded innovation '{innovation_id}': {innovation_type} '{name}' "
            f"by {proposed_by}"
        )
        
        return innovation
    
    def mark_innovation_tested(
        self,
        innovation_id: str,
        success_metrics: Dict[str, float],
    ) -> InnovationRecord:
        """Mark innovation as tested."""
        innovation = next((i for i in self._innovations if i.innovation_id == innovation_id), None)
        if not innovation:
            raise ValueError(f"Innovation '{innovation_id}' not found")
        
        innovation.tested = True
        innovation.success_metrics = success_metrics
        
        logger.info(f"Innovation '{innovation_id}' tested with metrics: {success_metrics}")
        
        return innovation
    
    def mark_innovation_promoted(
        self,
        innovation_id: str,
    ) -> InnovationRecord:
        """Mark innovation as successfully promoted."""
        innovation = next((i for i in self._innovations if i.innovation_id == innovation_id), None)
        if not innovation:
            raise ValueError(f"Innovation '{innovation_id}' not found")
        
        innovation.promoted = True
        
        # Update promotion rate
        self._update_promotion_rate()
        
        logger.info(f"Innovation '{innovation_id}' promoted to production")
        
        return innovation
    
    def add_pareto_point(
        self,
        strategy_id: str,
        agent_id: str,
        dimensions: Dict[str, float],
    ) -> ParetoPoint:
        """Add a point to Pareto frontier analysis."""
        import hashlib
        point_id = hashlib.md5(
            f"{strategy_id}_{agent_id}_{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        point = ParetoPoint(
            point_id=point_id,
            timestamp=datetime.utcnow(),
            strategy_id=strategy_id,
            agent_id=agent_id,
            dimensions=dimensions,
        )
        
        self._pareto_frontier.append(point)
        
        # Update domination status
        self._update_pareto_domination()
        
        # Compute frontier shift
        self._compute_frontier_shift()
        
        logger.info(
            f"Added Pareto point '{point_id}': {strategy_id} with dimensions {dimensions}"
        )
        
        return point
    
    def _update_innovation_rate(self) -> None:
        """Update innovation rate metric."""
        # Count innovations in last 7 days
        cutoff = datetime.utcnow() - timedelta(days=7)
        recent_innovations = [
            i for i in self._innovations
            if i.timestamp >= cutoff
        ]
        
        innovation_rate = len(recent_innovations)
        
        self.update_evolution_metric("innovation_rate", innovation_rate)
    
    def _update_promotion_rate(self) -> None:
        """Update promotion rate metric."""
        tested = [i for i in self._innovations if i.tested]
        promoted = [i for i in self._innovations if i.promoted]
        
        if tested:
            promotion_rate = len(promoted) / len(tested)
            self.update_evolution_metric("promotion_rate", promotion_rate)
    
    def _update_pareto_domination(self) -> None:
        """Update domination status for Pareto points."""
        points = self._pareto_frontier
        
        for i, point1 in enumerate(points):
            point1.dominated = False
            
            for j, point2 in enumerate(points):
                if i == j:
                    continue
                
                # Check if point2 dominates point1
                if self._dominates(point2.dimensions, point1.dimensions):
                    point1.dominated = True
                    break
    
    def _dominates(
        self,
        dims1: Dict[str, float],
        dims2: Dict[str, float],
    ) -> bool:
        """Check if dims1 dominates dims2 (Pareto dominance)."""
        # Assumes higher is better for all dimensions
        better_in_all = all(
            dims1.get(k, 0) >= dims2.get(k, 0)
            for k in dims2.keys()
        )
        
        better_in_some = any(
            dims1.get(k, 0) > dims2.get(k, 0)
            for k in dims2.keys()
        )
        
        return better_in_all and better_in_some
    
    def _compute_frontier_shift(self) -> None:
        """Compute movement of Pareto frontier."""
        if len(self._pareto_frontier) < 10:
            return
        
        # Compare recent frontier to older frontier
        cutoff = datetime.utcnow() - timedelta(days=30)
        
        recent_points = [p for p in self._pareto_frontier if p.timestamp >= cutoff and not p.dominated]
        older_points = [p for p in self._pareto_frontier if p.timestamp < cutoff and not p.dominated]
        
        if not recent_points or not older_points:
            return
        
        # Compute average improvement across dimensions
        improvements = []
        
        for dim in recent_points[0].dimensions.keys():
            recent_avg = np.mean([p.dimensions.get(dim, 0) for p in recent_points])
            older_avg = np.mean([p.dimensions.get(dim, 0) for p in older_points])
            
            if older_avg > 0:
                improvement = (recent_avg - older_avg) / older_avg
                improvements.append(improvement)
        
        if improvements:
            frontier_shift = np.mean(improvements)
            self.update_evolution_metric("frontier_shift", frontier_shift)
    
    def get_scaling_law_analysis(
        self,
        metric_id: str,
    ) -> Dict[str, Any]:
        """Get scaling law analysis for metric."""
        if metric_id not in self._scaling_law_metrics:
            raise ValueError(f"Scaling law metric '{metric_id}' not found")
        
        metric = self._scaling_law_metrics[metric_id]
        
        if len(metric.data_points) < 3:
            return {
                "metric_id": metric_id,
                "name": metric.name,
                "data_points": len(metric.data_points),
                "analysis": "Insufficient data for analysis",
            }
        
        # Sort by x-axis
        sorted_points = sorted(metric.data_points, key=lambda p: p[0])
        
        x_values = np.array([p[0] for p in sorted_points])
        y_values = np.array([p[1] for p in sorted_points])
        
        # Fit power law: y = a * x^b
        log_x = np.log(x_values + 1e-10)
        log_y = np.log(y_values + 1e-10)
        
        coeffs = np.polyfit(log_x, log_y, 1)
        b = coeffs[0]
        a = np.exp(coeffs[1])
        
        # Compute R^2
        y_pred = a * (x_values ** b)
        ss_res = np.sum((y_values - y_pred) ** 2)
        ss_tot = np.sum((y_values - np.mean(y_values)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        
        # Check for diminishing returns
        marginal_improvements = []
        for i in range(1, len(sorted_points)):
            x1, y1 = sorted_points[i-1]
            x2, y2 = sorted_points[i]
            if x2 > x1:
                marginal = (y2 - y1) / (x2 - x1)
                marginal_improvements.append(marginal)
        
        diminishing_returns = False
        if marginal_improvements and metric.diminishing_returns_threshold:
            recent_marginal = marginal_improvements[-1]
            diminishing_returns = recent_marginal < metric.diminishing_returns_threshold
        
        return {
            "metric_id": metric_id,
            "name": metric.name,
            "data_points": len(metric.data_points),
            "power_law_exponent": b,
            "power_law_coefficient": a,
            "r_squared": r_squared,
            "diminishing_returns": diminishing_returns,
            "recent_marginal_improvement": marginal_improvements[-1] if marginal_improvements else None,
            "x_range": (float(x_values.min()), float(x_values.max())),
            "y_range": (float(y_values.min()), float(y_values.max())),
        }
    
    def get_evolution_summary(self) -> Dict[str, Any]:
        """Get evolution metrics summary."""
        return {
            metric_id: {
                "name": metric.name,
                "current_value": metric.current_value,
                "target_value": metric.target_value,
                "trend": metric.trend,
                "on_track": metric.current_value >= metric.target_value if metric.target_value else None,
            }
            for metric_id, metric in self._evolution_metrics.items()
        }
    
    def get_swarm_health_summary(self) -> Dict[str, Any]:
        """Get swarm health metrics summary."""
        return {
            metric_id: {
                "name": metric.name,
                "current_value": metric.current_value,
                "threshold": metric.threshold,
                "healthy": metric.healthy,
            }
            for metric_id, metric in self._swarm_health_metrics.items()
        }
    
    def get_pareto_frontier(
        self,
        dimensions: Optional[List[str]] = None,
    ) -> List[ParetoPoint]:
        """Get current Pareto frontier (non-dominated points)."""
        frontier = [p for p in self._pareto_frontier if not p.dominated]
        
        if dimensions:
            # Filter to only include points with specified dimensions
            frontier = [
                p for p in frontier
                if all(dim in p.dimensions for dim in dimensions)
            ]
        
        return frontier
    
    def get_growth_dashboard(self) -> Dict[str, Any]:
        """Get comprehensive growth metrics dashboard."""
        return {
            "scaling_laws": {
                metric_id: self.get_scaling_law_analysis(metric_id)
                for metric_id in self._scaling_law_metrics.keys()
            },
            "evolution": self.get_evolution_summary(),
            "swarm_health": self.get_swarm_health_summary(),
            "pareto_frontier": {
                "total_points": len(self._pareto_frontier),
                "frontier_points": len([p for p in self._pareto_frontier if not p.dominated]),
                "dominated_points": len([p for p in self._pareto_frontier if p.dominated]),
            },
            "innovations": {
                "total": len(self._innovations),
                "tested": len([i for i in self._innovations if i.tested]),
                "promoted": len([i for i in self._innovations if i.promoted]),
            },
        }
    
    def _load_metrics(self) -> None:
        """Load metrics from disk."""
        if not self.metrics_file.exists():
            return
        
        try:
            with open(self.metrics_file, 'r') as f:
                data = json.load(f)
            
            # Load scaling law metrics
            for metric_data in data.get("scaling_law_metrics", []):
                metric = self._scaling_law_metrics.get(metric_data["metric_id"])
                if metric:
                    metric.data_points = [tuple(p) for p in metric_data["data_points"]]
                    if metric_data.get("last_updated"):
                        metric.last_updated = datetime.fromisoformat(metric_data["last_updated"])
            
            # Load evolution metrics
            for metric_data in data.get("evolution_metrics", []):
                metric = self._evolution_metrics.get(metric_data["metric_id"])
                if metric:
                    metric.current_value = metric_data["current_value"]
                    metric.history = [
                        (datetime.fromisoformat(t), v)
                        for t, v in metric_data["history"]
                    ]
                    metric.trend = metric_data.get("trend", "stable")
            
            logger.info("Loaded growth metrics from disk")
        
        except Exception as e:
            logger.error(f"Failed to load growth metrics: {e}")
    
    def _save_metrics(self) -> None:
        """Save metrics to disk."""
        try:
            data = {
                "scaling_law_metrics": [
                    {
                        "metric_id": metric.metric_id,
                        "name": metric.name,
                        "x_axis": metric.x_axis,
                        "y_axis": metric.y_axis,
                        "data_points": metric.data_points,
                        "last_updated": metric.last_updated.isoformat() if metric.last_updated else None,
                    }
                    for metric in self._scaling_law_metrics.values()
                ],
                "evolution_metrics": [
                    {
                        "metric_id": metric.metric_id,
                        "name": metric.name,
                        "current_value": metric.current_value,
                        "history": [
                            (t.isoformat(), v) for t, v in metric.history
                        ],
                        "trend": metric.trend,
                    }
                    for metric in self._evolution_metrics.values()
                ],
            }
            
            with open(self.metrics_file, 'w') as f:
                json.dump(data, f, indent=2)
        
        except Exception as e:
            logger.error(f"Failed to save growth metrics: {e}")


_growth_metrics_tracker: Optional[GrowthMetricsTracker] = None


def get_growth_metrics_tracker() -> GrowthMetricsTracker:
    """Get global GrowthMetricsTracker instance."""
    global _growth_metrics_tracker
    if _growth_metrics_tracker is None:
        _growth_metrics_tracker = GrowthMetricsTracker()
    return _growth_metrics_tracker
