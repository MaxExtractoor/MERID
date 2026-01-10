"""Stage 6.5: Adversarial hardening against data poisoning attacks."""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

from utils.logger import get_logger

logger = get_logger("core.adversarial")


@dataclass
class TemporalProfile:
    """Temporal consistency tracking for a source+metric pair."""

    source: str
    metric: str
    rolling_values: Deque[float] = field(default_factory=lambda: deque(maxlen=20))
    rolling_mean: float = 0.0
    rolling_std: float = 0.0
    max_slope: float = 0.0032  # % per minute (default)
    suspicion_counter: int = 0
    last_updated: float = field(default_factory=time.time)

    def update(self, value: float) -> bool:
        """
        Update temporal profile and check for violation.
        Returns True if temporal violation detected.
        """
        now = time.time()
        elapsed_minutes = (now - self.last_updated) / 60.0

        # Check slope violation before updating
        violation = False
        if self.rolling_mean > 0 and len(self.rolling_values) >= 3:
            slope = abs(value - self.rolling_mean) / self.rolling_mean
            if slope > self.max_slope * max(elapsed_minutes, 1.0):
                violation = True
                self.suspicion_counter += 1
                logger.warning(
                    "Temporal violation: %s/%s slope=%.4f exceeds max=%.4f",
                    self.source,
                    self.metric,
                    slope,
                    self.max_slope,
                )

        # Update rolling stats
        self.rolling_values.append(value)
        if len(self.rolling_values) >= 2:
            self.rolling_mean = float(np.mean(self.rolling_values))
            self.rolling_std = float(np.std(self.rolling_values))

        self.last_updated = now
        return violation


@dataclass
class SourceAgreementGraph:
    """Collusion/Sybil detection via source agreement correlation."""

    agreement_matrix: Dict[Tuple[str, str], float] = field(default_factory=dict)
    delta_history: Dict[str, Deque[float]] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=50)))
    suspect_clusters: List[List[str]] = field(default_factory=list)

    def record_delta(self, source: str, delta: float) -> None:
        """Record a delta (deviation from consensus) for a source."""
        self.delta_history[source].append(delta)

    def compute_agreements(self) -> None:
        """Compute pairwise agreement correlations between sources."""
        sources = list(self.delta_history.keys())
        for i, src_a in enumerate(sources):
            for src_b in sources[i + 1 :]:
                if len(self.delta_history[src_a]) >= 10 and len(self.delta_history[src_b]) >= 10:
                    corr = np.corrcoef(
                        list(self.delta_history[src_a])[-10:],
                        list(self.delta_history[src_b])[-10:],
                    )[0, 1]
                    if not np.isnan(corr):
                        self.agreement_matrix[(src_a, src_b)] = corr

    def detect_collusion(self, threshold_internal: float = 0.9, threshold_external: float = -0.5) -> List[List[str]]:
        """
        Detect suspect clusters: high mutual agreement, low agreement with majority.
        Returns list of suspect source clusters.
        """
        self.compute_agreements()
        sources = list(self.delta_history.keys())
        clusters = []

        # Simple clustering: find pairs with high agreement
        for (src_a, src_b), corr in self.agreement_matrix.items():
            if corr > threshold_internal:
                # Check if cluster disagrees with global
                global_sources = [s for s in sources if s not in (src_a, src_b)]
                if global_sources:
                    cluster_vs_global = []
                    for global_src in global_sources:
                        pair_key_a = tuple(sorted([src_a, global_src]))
                        pair_key_b = tuple(sorted([src_b, global_src]))
                        if pair_key_a in self.agreement_matrix:
                            cluster_vs_global.append(self.agreement_matrix[pair_key_a])
                        if pair_key_b in self.agreement_matrix:
                            cluster_vs_global.append(self.agreement_matrix[pair_key_b])
                    if cluster_vs_global and np.mean(cluster_vs_global) < threshold_external:
                        cluster = [src_a, src_b]
                        if cluster not in clusters:
                            clusters.append(cluster)
                            logger.warning("Collusion cluster detected: %s (internal=%.3f)", cluster, corr)

        self.suspect_clusters = clusters
        return clusters


@dataclass
class ShadowConsensus:
    """Parallel consensus path using median and static priors (canary)."""

    primary_values: List[float] = field(default_factory=list)
    shadow_values: List[float] = field(default_factory=list)
    divergence_threshold: float = 0.15  # 15% divergence triggers alert
    poisoning_suspected: bool = False

    def compute(self, claims: List[Dict[str, float]]) -> Tuple[float, float, bool]:
        """
        Compute primary (weighted mean) and shadow (median) consensus.
        Returns (primary, shadow, divergence_alert).
        """
        if not claims:
            return 0.0, 0.0, False

        # Primary: weighted mean
        weights = [c.get("weight", 1.0) for c in claims]
        values = [c.get("value", 0.0) for c in claims]
        primary = np.average(values, weights=weights) if sum(weights) > 0 else np.mean(values)

        # Shadow: simple median (no weights)
        shadow = float(np.median(values))

        # Divergence check
        if primary > 0:
            divergence = abs(primary - shadow) / primary
            alert = divergence > self.divergence_threshold
            if alert and not self.poisoning_suspected:
                self.poisoning_suspected = True
                logger.error(
                    "POISONING ALERT: Shadow consensus divergence %.3f exceeds threshold %.3f (primary=%.4f, shadow=%.4f)",
                    divergence,
                    self.divergence_threshold,
                    primary,
                    shadow,
                )
            return primary, shadow, alert

        return primary, shadow, False


class AdversarialHardeningLayer:
    """Stage 6.5: Adversarial hardening orchestrator."""

    def __init__(
        self,
        min_effective_sources: int = 3,
        temporal_max_slope: float = 0.0032,
        confidence_inversion_threshold: float = 0.6,
    ) -> None:
        self.min_effective_sources = min_effective_sources
        self.temporal_max_slope = temporal_max_slope
        self.confidence_inversion_threshold = confidence_inversion_threshold

        self.temporal_profiles: Dict[Tuple[str, str], TemporalProfile] = {}
        self.agreement_graph = SourceAgreementGraph()
        self.shadow_consensus = ShadowConsensus()
        self.trust_updates_frozen = False
        self.poisoning_alert_count = 0

    def check_temporal_consistency(self, source: str, metric: str, value: float) -> bool:
        """
        Check temporal consistency for a claim.
        Returns True if violation detected.
        """
        key = (source, metric)
        if key not in self.temporal_profiles:
            self.temporal_profiles[key] = TemporalProfile(
                source=source,
                metric=metric,
                max_slope=self.temporal_max_slope,
            )
        return self.temporal_profiles[key].update(value)

    def apply_confidence_inversion_penalty(self, claim_confidence: float, source_reliability: float) -> float:
        """
        Apply confidence inversion test: penalize high-confidence claims from low-reliability sources.
        Returns penalty multiplier [0.5, 1.0].
        """
        if claim_confidence > 0.9 and source_reliability < self.confidence_inversion_threshold:
            logger.debug(
                "Confidence inversion penalty applied: conf=%.3f, reliability=%.3f",
                claim_confidence,
                source_reliability,
            )
            return 0.5
        return 1.0

    def check_consensus_floor(self, source_weights: List[float]) -> float:
        """
        Check effective source count and apply consensus confidence penalty if too low.
        Returns confidence multiplier [0.5, 1.0].
        """
        effective_n = sum(1 for w in source_weights if w > 0.1)
        if effective_n < self.min_effective_sources:
            logger.warning(
                "Low epistemic diversity: effective_sources=%d < min=%d",
                effective_n,
                self.min_effective_sources,
            )
            return 0.5
        return 1.0

    def run_shadow_consensus_check(self, claims: List[Dict[str, float]]) -> Tuple[float, float, bool]:
        """
        Run shadow consensus and check for divergence.
        Returns (primary, shadow, poisoning_alert).
        """
        primary, shadow, alert = self.shadow_consensus.compute(claims)
        if alert:
            self.poisoning_alert_count += 1
            self.trust_updates_frozen = True
            logger.error("Trust updates FROZEN due to shadow consensus divergence")
        return primary, shadow, alert

    def record_source_delta(self, source: str, delta: float) -> None:
        """Record deviation from consensus for collusion detection."""
        self.agreement_graph.record_delta(source, delta)

    def detect_collusion_clusters(self) -> List[List[str]]:
        """Detect and return suspect collusion clusters."""
        return self.agreement_graph.detect_collusion()

    def reset_poisoning_state(self) -> None:
        """Reset poisoning alert state after clean cycles."""
        if self.poisoning_alert_count > 0:
            logger.info("Resetting poisoning state after clean cycles")
        self.trust_updates_frozen = False
        self.poisoning_alert_count = 0
        self.shadow_consensus.poisoning_suspected = False

    def hardening_status(self) -> Dict[str, any]:
        """Return current hardening status for observability."""
        return {
            "trust_updates_frozen": self.trust_updates_frozen,
            "poisoning_alert_count": self.poisoning_alert_count,
            "temporal_profiles_tracked": len(self.temporal_profiles),
            "suspect_clusters": self.agreement_graph.suspect_clusters,
            "shadow_divergence_suspected": self.shadow_consensus.poisoning_suspected,
        }


# Global singleton
_hardening_layer = AdversarialHardeningLayer()


def get_hardening_layer() -> AdversarialHardeningLayer:
    """Access the global adversarial hardening layer."""
    return _hardening_layer
