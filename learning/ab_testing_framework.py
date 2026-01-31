"""
A/B testing framework for agent and prompt experiments.

Provides experiment lifecycle management, metric collection, and significance
evaluation without relying on external services. Designed for rapid iteration
inside the MERID swarm where multiple variants need to be compared safely.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import sqrt
from typing import Dict, List, Optional, Tuple
import logging
import uuid


logger = logging.getLogger(__name__)


@dataclass
class ABTestVariant:
    """Single experiment variant."""

    name: str
    description: str
    samples: int = 0
    metric_sum: float = 0.0
    metric_squared_sum: float = 0.0
    last_updated: datetime = field(default_factory=datetime.utcnow)

    def record(self, metric_value: float, sample_size: int = 1) -> None:
        self.samples += sample_size
        self.metric_sum += metric_value * sample_size
        self.metric_squared_sum += (metric_value ** 2) * sample_size
        self.last_updated = datetime.utcnow()

    @property
    def mean(self) -> float:
        return self.metric_sum / self.samples if self.samples else 0.0

    @property
    def variance(self) -> float:
        if self.samples <= 1:
            return 0.0
        numerator = self.metric_squared_sum - (self.metric_sum ** 2) / self.samples
        return numerator / (self.samples - 1)


@dataclass
class ABTestExperiment:
    """Full experiment definition."""

    experiment_id: str
    name: str
    hypothesis: str
    success_metric: str
    created_at: datetime
    min_duration: timedelta
    variants: Dict[str, ABTestVariant] = field(default_factory=dict)
    metadata: Dict[str, str] = field(default_factory=dict)
    completed: bool = False
    winning_variant: Optional[str] = None


class ABTestingFramework:
    """Manage and evaluate concurrent agent experiments."""

    def __init__(self) -> None:
        self._experiments: Dict[str, ABTestExperiment] = {}

    def start_experiment(
        self,
        name: str,
        hypothesis: str,
        success_metric: str,
        variants: List[Tuple[str, str]],
        min_duration_hours: float = 4.0,
        metadata: Optional[Dict[str, str]] = None,
    ) -> ABTestExperiment:
        """Start a new experiment with two or more variants."""
        if len(variants) < 2:
            raise ValueError("A/B experiments require at least two variants")

        experiment_id = uuid.uuid4().hex[:12]
        experiment = ABTestExperiment(
            experiment_id=experiment_id,
            name=name,
            hypothesis=hypothesis,
            success_metric=success_metric,
            created_at=datetime.utcnow(),
            min_duration=timedelta(hours=min_duration_hours),
            metadata=metadata or {},
        )

        for variant_name, description in variants:
            experiment.variants[variant_name] = ABTestVariant(
                name=variant_name,
                description=description,
            )

        self._experiments[experiment_id] = experiment
        logger.info("Started experiment %s (%s)", experiment_id, name)
        return experiment

    def record_observation(
        self,
        experiment_id: str,
        variant_name: str,
        metric_value: float,
        sample_size: int = 1,
    ) -> None:
        """Record a metric observation for a variant."""
        experiment = self._experiments.get(experiment_id)
        if not experiment:
            raise KeyError(f"Experiment '{experiment_id}' not found")

        variant = experiment.variants.get(variant_name)
        if not variant:
            raise KeyError(f"Variant '{variant_name}' not registered in experiment '{experiment_id}'")

        variant.record(metric_value, sample_size=sample_size)
        logger.debug(
            "Observation recorded for experiment %s variant %s value %.4f",
            experiment_id,
            variant_name,
            metric_value,
        )

    def evaluate_experiment(
        self,
        experiment_id: str,
        min_sample_size: int = 20,
    ) -> Dict[str, Optional[str]]:
        """
        Evaluate experiment winners using Welch's t-test between all variant pairs.

        Returns dictionary with winning_variant and supporting info. Experiments
        remain active until explicitly closed, allowing repeated evaluations as
        new data arrives.
        """
        experiment = self._experiments.get(experiment_id)
        if not experiment:
            raise KeyError(f"Experiment '{experiment_id}' not found")

        if datetime.utcnow() - experiment.created_at < experiment.min_duration:
            return {"winning_variant": None, "reason": "duration_not_met"}

        underpowered = any(v.samples < min_sample_size for v in experiment.variants.values())
        if underpowered:
            return {"winning_variant": None, "reason": "insufficient_samples"}

        best_variant = None
        best_mean = float("-inf")
        significance_won = True

        for variant_name, variant in experiment.variants.items():
            if variant.mean > best_mean:
                best_mean = variant.mean
                best_variant = variant_name

        # Validate significance by ensuring best variant beats others with t-test
        best = experiment.variants[best_variant]
        for other_name, other in experiment.variants.items():
            if other_name == best_variant:
                continue
            p_value = self._welch_t_test(best, other)
            if p_value is None or p_value > 0.05:
                significance_won = False
                break

        if significance_won:
            experiment.completed = True
            experiment.winning_variant = best_variant

        return {
            "winning_variant": best_variant if significance_won else None,
            "significant": significance_won,
            "means": {name: variant.mean for name, variant in experiment.variants.items()},
            "samples": {name: variant.samples for name, variant in experiment.variants.items()},
        }

    def get_experiment(self, experiment_id: str) -> Optional[ABTestExperiment]:
        return self._experiments.get(experiment_id)

    def get_active_experiments(self) -> List[ABTestExperiment]:
        return [exp for exp in self._experiments.values() if not exp.completed]

    @staticmethod
    def _welch_t_test(variant_a: ABTestVariant, variant_b: ABTestVariant) -> Optional[float]:
        """Return approximate two-tailed p-value using Welch's t-test."""
        if variant_a.samples < 2 or variant_b.samples < 2:
            return None

        mean_diff = variant_a.mean - variant_b.mean
        var_a = variant_a.variance
        var_b = variant_b.variance
        if var_a == 0 and var_b == 0:
            return None

        numerator = mean_diff
        denominator = sqrt(var_a / variant_a.samples + var_b / variant_b.samples)
        if denominator == 0:
            return None

        t_stat = numerator / denominator
        df_numerator = (var_a / variant_a.samples + var_b / variant_b.samples) ** 2
        df_denominator = (var_a ** 2) / (variant_a.samples ** 2 * (variant_a.samples - 1))
        df_denominator += (var_b ** 2) / (variant_b.samples ** 2 * (variant_b.samples - 1))
        if df_denominator == 0:
            return None
        degrees_of_freedom = df_numerator / df_denominator

        # Approximate p-value using survival function of t distribution via beta function
        # For simplicity, use a fallback based on large-sample normal approximation.
        from math import erf

        z = abs(t_stat)
        p_value = 2 * (1 - 0.5 * (1 + erf(z / sqrt(2))))
        logger.debug(
            "Welch test between variants: t=%.4f, df=%.2f, p=%.4f",
            t_stat,
            degrees_of_freedom,
            p_value,
        )
        return p_value


_ab_testing_framework: Optional[ABTestingFramework] = None


def get_ab_testing_framework() -> ABTestingFramework:
    global _ab_testing_framework
    if _ab_testing_framework is None:
        _ab_testing_framework = ABTestingFramework()
    return _ab_testing_framework
