"""Stage 6.5: Adversarial hardening against data poisoning attacks."""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple, Set

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
    window_size: int = 20
    min_samples: int = 8

    def record_delta(self, source: str, delta: float) -> None:
        """Record a delta (deviation from consensus) for a source."""
        self.delta_history[source].append(delta)

    def compute_agreements(self) -> None:
        """Compute pairwise agreement correlations between sources."""
        self.agreement_matrix.clear()
        sources = sorted(self.delta_history.keys())
        for i, src_a in enumerate(sources):
            series_a = self._get_recent_series(src_a)
            if len(series_a) < self.min_samples:
                continue
            for src_b in sources[i + 1 :]:
                series_b = self._get_recent_series(src_b)
                if len(series_b) < self.min_samples:
                    continue
                aligned_len = min(len(series_a), len(series_b))
                if aligned_len < self.min_samples:
                    continue
                norm_a = self._normalize_series(series_a[-aligned_len:])
                norm_b = self._normalize_series(series_b[-aligned_len:])
                if norm_a.size == 0 or norm_b.size == 0:
                    continue
                corr = self._compute_correlation(norm_a, norm_b)
                if corr is None:
                    continue
                key = tuple(sorted((src_a, src_b)))
                self.agreement_matrix[key] = float(max(min(corr, 1.0), -1.0))

    def detect_collusion(
        self,
        threshold_internal: float = 0.8,
        threshold_external: float = 0.0,
        min_cluster_size: int = 2,
    ) -> List[List[str]]:
        """
        Detect suspect clusters: high mutual agreement, low agreement with majority.
        Returns list of suspect source clusters.
        """
        self.compute_agreements()
        sources = list(self.delta_history.keys())
        adjacency: Dict[str, Set[str]] = defaultdict(set)
        for (src_a, src_b), corr in self.agreement_matrix.items():
            if corr >= threshold_internal:
                adjacency[src_a].add(src_b)
                adjacency[src_b].add(src_a)

        clusters: List[List[str]] = []
        visited: Set[str] = set()

        for node in adjacency.keys():
            if node in visited:
                continue
            stack = [node]
            cluster_nodes: List[str] = []
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                cluster_nodes.append(current)
                stack.extend(adjacency[current] - visited)

            if len(cluster_nodes) < min_cluster_size:
                continue

            cluster_nodes.sort()
            outsider_corrs: List[float] = []
            for member in cluster_nodes:
                for outsider in sources:
                    if outsider in cluster_nodes:
                        continue
                    pair_key = tuple(sorted((member, outsider)))
                    if pair_key in self.agreement_matrix:
                        outsider_corrs.append(self.agreement_matrix[pair_key])

            if outsider_corrs:
                if np.mean(outsider_corrs) <= threshold_external:
                    clusters.append(cluster_nodes)
                    logger.warning(
                        "Collusion cluster detected: %s (external_avg=%.3f)",
                        cluster_nodes,
                        float(np.mean(outsider_corrs)),
                    )
            else:
                # No global comparison available—default to conservative flagging.
                clusters.append(cluster_nodes)
                logger.warning(
                    "Collusion cluster detected without external comparators: %s",
                    cluster_nodes,
                )

        self.suspect_clusters = clusters
        return clusters

    def _get_recent_series(self, source: str) -> List[float]:
        return list(self.delta_history[source])[-self.window_size :]

    def _normalize_series(self, series: List[float]) -> np.ndarray:
        arr = np.asarray(series, dtype=float)
        if arr.size == 0:
            return arr
        std = np.std(arr)
        if std < 1e-6:
            if np.allclose(arr, 0.0):
                return np.asarray([], dtype=float)
            signs = np.sign(arr)
            signs[signs == 0] = 1.0
            return signs
        mean = np.mean(arr)
        return (arr - mean) / std

    def _compute_correlation(self, series_a: np.ndarray, series_b: np.ndarray) -> Optional[float]:
        if series_a.size == 0 or series_b.size == 0:
            return None
        if series_a.size != series_b.size:
            length = min(series_a.size, series_b.size)
            series_a = series_a[-length:]
            series_b = series_b[-length:]
        std_a = np.std(series_a)
        std_b = np.std(series_b)
        if std_a < 1e-6 or std_b < 1e-6:
            # Fallback to sign agreement score in [-1, 1]
            signs_a = np.sign(series_a)
            signs_b = np.sign(series_b)
            matches = np.mean(signs_a == signs_b)
            return (matches * 2.0) - 1.0
        corr = np.corrcoef(series_a, series_b)[0, 1]
        if np.isnan(corr):
            return None
        return corr


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
        self.temporal_profiles.clear()
        # Clear residual collusion history so clean cycles are evaluated fresh
        self.agreement_graph.delta_history.clear()
        self.agreement_graph.agreement_matrix.clear()
        self.agreement_graph.suspect_clusters = []

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
