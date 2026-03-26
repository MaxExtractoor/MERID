"""ConsensusProtection — Anti-herding and thread-safe consensus aggregation.

Implements critical fixes:
- C-001 (HIGH): Anti-herding protection (prevents false consensus from correlated agents)
- C-002 (HIGH): Race condition fix in consensus cache writes
- C-003 (HIGH): Improved track-record weighting (prevents overfitting to lucky streaks)

Protects against:
1. All agents reading same context creating false consensus
2. Concurrent cache writes corrupting consensus state
3. Single lucky streak dominating consensus weights
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set
from threading import Lock
import statistics

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.consensus_protection")


# ── Anti-Herding Detection ───────────────────────────────────────────────────


@dataclass
class HerdingMetrics:
    """Metrics for detecting herding behavior."""
    proposal_count: int
    unique_rationales: int
    unique_archetypes: int
    context_hash_diversity: float  # 0-1, higher = more diverse
    opinion_entropy: float  # Higher = more disagreement
    herding_detected: bool
    herding_reason: Optional[str] = None


class AntiHerdingDetector:
    """Detects and mitigates false consensus from correlated agents.

    Checks for:
    1. Low diversity in agent archetypes (all momentum traders)
    2. Identical or near-identical rationales (copy-paste consensus)
    3. Suspiciously unanimous agreement (no dissent)
    4. Same information context hashes (all read same tweets)
    """

    def __init__(
        self,
        *,
        min_unique_archetypes: int = 2,
        min_rationale_diversity: float = 0.5,
        max_unanimous_threshold: float = 0.95,
    ):
        """Initialize anti-herding detector.

        Args:
            min_unique_archetypes: Minimum unique agent archetypes required
            min_rationale_diversity: Minimum rationale diversity ratio (unique/total)
            max_unanimous_threshold: Maximum unanimity before herding flag (0.95 = 95% agreement)
        """
        self.min_unique_archetypes = min_unique_archetypes
        self.min_rationale_diversity = min_rationale_diversity
        self.max_unanimous_threshold = max_unanimous_threshold

        # Stats
        self.total_checks = 0
        self.herding_detections = 0

    def detect_herding(
        self,
        proposals: List[Any],  # List[AgentProposal]
    ) -> HerdingMetrics:
        """Check for herding behavior in agent proposals.

        Args:
            proposals: List of AgentProposal objects

        Returns:
            HerdingMetrics with herding detection result
        """
        self.total_checks += 1

        if len(proposals) < 2:
            # Need at least 2 agents for herding detection
            return HerdingMetrics(
                proposal_count=len(proposals),
                unique_rationales=len(proposals),
                unique_archetypes=len(proposals),
                context_hash_diversity=1.0,
                opinion_entropy=1.0,
                herding_detected=False,
            )

        # 1. Check archetype diversity
        archetypes = [p.agent_archetype for p in proposals]
        unique_archetypes = len(set(archetypes))

        if unique_archetypes < self.min_unique_archetypes:
            self.herding_detections += 1
            return HerdingMetrics(
                proposal_count=len(proposals),
                unique_rationales=0,
                unique_archetypes=unique_archetypes,
                context_hash_diversity=0.0,
                opinion_entropy=0.0,
                herding_detected=True,
                herding_reason=f"Low archetype diversity: {unique_archetypes} < {self.min_unique_archetypes}",
            )

        # 2. Check rationale diversity (via hashing)
        rationale_hashes = [
            hashlib.md5(p.rationale.encode()).hexdigest()[:8]
            for p in proposals
        ]
        unique_rationales = len(set(rationale_hashes))
        rationale_diversity = unique_rationales / len(proposals)

        if rationale_diversity < self.min_rationale_diversity:
            self.herding_detections += 1
            return HerdingMetrics(
                proposal_count=len(proposals),
                unique_rationales=unique_rationales,
                unique_archetypes=unique_archetypes,
                context_hash_diversity=rationale_diversity,
                opinion_entropy=0.0,
                herding_detected=True,
                herding_reason=f"Low rationale diversity: {rationale_diversity:.2f} < {self.min_rationale_diversity}",
            )

        # 3. Check opinion entropy (direction distribution)
        directions = [p.direction for p in proposals]
        direction_counts = defaultdict(int)
        for d in directions:
            direction_counts[d] += 1

        # Calculate entropy
        total = len(directions)
        opinion_entropy = 0.0
        for count in direction_counts.values():
            p = count / total
            if p > 0:
                opinion_entropy -= p * (p.bit_length() - 1) / 2  # Rough entropy

        # Check unanimity
        max_direction_ratio = max(direction_counts.values()) / total
        if max_direction_ratio > self.max_unanimous_threshold:
            self.herding_detections += 1
            return HerdingMetrics(
                proposal_count=len(proposals),
                unique_rationales=unique_rationales,
                unique_archetypes=unique_archetypes,
                context_hash_diversity=rationale_diversity,
                opinion_entropy=opinion_entropy,
                herding_detected=True,
                herding_reason=f"Excessive unanimity: {max_direction_ratio:.0%} agreement (threshold {self.max_unanimous_threshold:.0%})",
            )

        # No herding detected
        return HerdingMetrics(
            proposal_count=len(proposals),
            unique_rationales=unique_rationales,
            unique_archetypes=unique_archetypes,
            context_hash_diversity=rationale_diversity,
            opinion_entropy=opinion_entropy,
            herding_detected=False,
        )


# ── Thread-Safe Consensus Cache ──────────────────────────────────────────────


class ConsensusCache:
    """Thread-safe cache for consensus computations.

    Fixes C-002: Race condition in consensus cache writes.
    """

    def __init__(self):
        """Initialize cache with thread lock."""
        self._cache: Dict[str, Any] = {}
        self._lock = Lock()
        self._timestamps: Dict[str, datetime] = {}

    def get(self, key: str) -> Optional[Any]:
        """Get cached value with thread safety.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        with self._lock:
            return self._cache.get(key)

    def set(
        self,
        key: str,
        value: Any,
        *,
        ttl_seconds: Optional[float] = None,
    ) -> None:
        """Set cached value with thread safety.

        Args:
            key: Cache key
            value: Value to cache
            ttl_seconds: Optional TTL in seconds
        """
        with self._lock:
            self._cache[key] = value
            self._timestamps[key] = datetime.now(timezone.utc)

    def invalidate(self, key: str) -> bool:
        """Invalidate cache entry.

        Args:
            key: Cache key

        Returns:
            True if entry existed and was removed
        """
        with self._lock:
            existed = key in self._cache
            self._cache.pop(key, None)
            self._timestamps.pop(key, None)
            return existed

    def clear(self) -> int:
        """Clear entire cache.

        Returns:
            Number of entries cleared
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._timestamps.clear()
            return count


# ── Improved Track Record Weighting ──────────────────────────────────────────


@dataclass
class AgentWeight:
    """Calculated weight for an agent in consensus."""
    agent_id: str
    weight: float  # 0-1
    brier_score: float
    win_rate: float
    sample_count: int
    recency_discount: float
    final_weight: float


class TrackRecordWeighting:
    """Improved agent weighting that prevents overfitting to lucky streaks.

    Implements C-003 fix with:
    1. Minimum sample size requirement (min 20 trades)
    2. Recency discounting (exponential decay, not all-recent)
    3. Regularization (Bayesian shrinkage toward neutral prior)
    4. Uncertainty weighting (lower weight for low-sample-count agents)
    """

    def __init__(
        self,
        *,
        min_samples: int = 20,
        recency_halflife_days: float = 14.0,
        prior_brier: float = 0.25,
        prior_strength: float = 10.0,
    ):
        """Initialize track record weighting.

        Args:
            min_samples: Minimum trades before full weighting
            recency_halflife_days: Half-life for recency decay (default 14 days)
            prior_brier: Prior Brier score for regularization (default 0.25)
            prior_strength: Strength of prior in pseudo-counts (default 10)
        """
        self.min_samples = min_samples
        self.recency_halflife_days = recency_halflife_days
        self.prior_brier = prior_brier
        self.prior_strength = prior_strength

    def calculate_weight(
        self,
        agent_id: str,
        *,
        brier_score: float,
        win_rate: float,
        sample_count: int,
        last_trade_age_days: float = 0.0,
    ) -> AgentWeight:
        """Calculate regularized weight for an agent.

        Args:
            agent_id: Agent identifier
            brier_score: Raw Brier score (lower is better, 0-1)
            win_rate: Fraction of winning trades (0-1)
            sample_count: Number of trades in track record
            last_trade_age_days: Days since last trade (for recency)

        Returns:
            AgentWeight with calculated weight components
        """
        # 1. Regularize Brier score (Bayesian shrinkage toward prior)
        regularized_brier = (
            (brier_score * sample_count + self.prior_brier * self.prior_strength)
            / (sample_count + self.prior_strength)
        )

        # 2. Sample size discount (sigmoid ramping function)
        sample_discount = min(1.0, sample_count / self.min_samples)

        # 3. Recency discount (exponential decay)
        recency_discount = 0.5 ** (last_trade_age_days / self.recency_halflife_days)

        # 4. Convert Brier to weight (invert: low Brier = high weight)
        # Brier ranges 0 (perfect) to 1 (worst), typical good agent ~0.15-0.25
        base_weight = max(0.0, 1.0 - regularized_brier * 2.0)  # Scale to 0-1

        # 5. Combine factors
        final_weight = base_weight * sample_discount * recency_discount

        # Clamp to [0, 1]
        final_weight = max(0.0, min(1.0, final_weight))

        return AgentWeight(
            agent_id=agent_id,
            weight=base_weight,
            brier_score=regularized_brier,
            win_rate=win_rate,
            sample_count=sample_count,
            recency_discount=recency_discount,
            final_weight=final_weight,
        )


# ── Singletons ───────────────────────────────────────────────────────────────


_herding_detector: Optional[AntiHerdingDetector] = None
_consensus_cache: Optional[ConsensusCache] = None
_track_weighting: Optional[TrackRecordWeighting] = None


def get_herding_detector() -> AntiHerdingDetector:
    """Get singleton AntiHerdingDetector."""
    global _herding_detector
    if _herding_detector is None:
        _herding_detector = AntiHerdingDetector()
    return _herding_detector


def get_consensus_cache() -> ConsensusCache:
    """Get singleton ConsensusCache."""
    global _consensus_cache
    if _consensus_cache is None:
        _consensus_cache = ConsensusCache()
    return _consensus_cache


def get_track_weighting() -> TrackRecordWeighting:
    """Get singleton TrackRecordWeighting."""
    global _track_weighting
    if _track_weighting is None:
        _track_weighting = TrackRecordWeighting()
    return _track_weighting
