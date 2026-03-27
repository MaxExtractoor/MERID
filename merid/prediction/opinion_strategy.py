"""Pluggable opinion scoring strategies for prediction market agents.

Provides:
  - OpinionStrategy (ABC): interface for computing agent probability estimates
  - HashBiasStrategy: deterministic hash-based bias (baseline/default)
  - MeanReversionStrategy: contrarian strategy that fades extreme market probs
  - CalibrationAwareStrategy: adjusts toward calibrated base rates

Each strategy takes an instrument + agent context and returns an estimated
probability, confidence, and reasoning tag.
"""

from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.opinion_strategy")


@dataclass
class OpinionExplanation:
    """Structured explanation for an opinion estimate.

    Designed as a model-agnostic explanation boundary: heuristic strategies
    populate these fields directly; future ML models (SHAP, LIME, etc.)
    convert their attributions into the same shape via a thin adapter.

    Fields:
        inputs_used: Normalized view of what the strategy looked at.
        contributions: Simple decomposition showing which components
            pulled the probability and by how much (sums to ~edge).
        rationale: Machine-readable tag describing the dominant logic.
    """
    inputs_used: Dict[str, Any] = field(default_factory=dict)
    contributions: Dict[str, float] = field(default_factory=dict)
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "inputs_used": self.inputs_used,
            "contributions": self.contributions,
            "rationale": self.rationale,
        }


@dataclass
class OpinionEstimate:
    """Output of an opinion strategy for a single instrument."""
    agent_prob: float          # Agent's estimated P(YES), 0–1
    confidence: float          # How confident the agent is in this estimate
    edge: float                # agent_prob - market_prob
    reasoning_tag: str         # Short tag describing the strategy's logic
    signal_sources: List[str]  # What data sources informed this estimate
    explanation: Optional[OpinionExplanation] = None  # Structured explanation

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "agent_prob": self.agent_prob,
            "confidence": self.confidence,
            "edge": self.edge,
            "reasoning_tag": self.reasoning_tag,
            "signal_sources": self.signal_sources,
        }
        if self.explanation:
            d["explanation"] = self.explanation.to_dict()
        return d


class OpinionStrategy(ABC):
    """Abstract base for opinion scoring strategies.

    Subclasses implement `estimate()` which takes market data and returns
    an OpinionEstimate. The agent calls this instead of hard-coding edge logic.
    """

    name: str = "base"
    min_edge: float = 0.02          # Minimum |edge| to emit an opinion
    min_market_prob: float = 0.01   # Skip markets below this
    max_market_prob: float = 0.99   # Skip markets above this
    max_confidence: float = 0.95    # Hard cap on emitted confidence

    @abstractmethod
    def estimate(
        self,
        agent_id: str,
        ticker: str,
        market_prob: float,
        category: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[OpinionEstimate]:
        """Compute an opinion estimate for a single instrument.

        Returns None if the strategy declines to opine (e.g., insufficient edge).
        """
        ...

    def should_skip(self, market_prob: float) -> bool:
        """Check if market probability is too extreme to opine on."""
        return market_prob <= self.min_market_prob or market_prob >= self.max_market_prob

    def _apply_confidence_clamp(
        self,
        confidence: float,
        explanation: "OpinionExplanation",
    ) -> float:
        """Clamp confidence to max_confidence and annotate rationale when active.

        When the clamp fires, appends ``confidence_clamped_at_{max}`` to the
        explanation rationale.  When it does NOT fire, the rationale is left
        untouched — no phantom "fallback" or "clamped" tag is ever added.
        """
        if confidence > self.max_confidence:
            explanation.rationale = (
                f"{explanation.rationale}|confidence_clamped_at_{self.max_confidence}"
            )
            return self.max_confidence
        return confidence


class HashBiasStrategy(OpinionStrategy):
    """Deterministic hash-based bias strategy (baseline).

    Generates a repeatable ±5% bias from agent_id + ticker, producing
    structurally valid opinions that prove the pipeline works. Not intended
    to be accurate — serves as the default until a calibrated model is available.
    """

    name = "hash_bias"

    def __init__(self, bias_range: float = 0.10, min_edge: float = 0.02, max_confidence: float = 0.95):
        self.bias_range = bias_range  # Total range (±half)
        self.min_edge = min_edge
        self.max_confidence = max_confidence

    def estimate(
        self,
        agent_id: str,
        ticker: str,
        market_prob: float,
        category: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[OpinionEstimate]:
        if self.should_skip(market_prob):
            return None

        seed = hashlib.md5(f"{agent_id}:{ticker}".encode()).hexdigest()
        bias = (int(seed[:4], 16) / 65535.0 - 0.5) * self.bias_range
        agent_prob = max(0.02, min(0.98, market_prob + bias))
        edge = agent_prob - market_prob

        if abs(edge) < self.min_edge:
            return None

        explanation = OpinionExplanation(
            inputs_used={
                "market_prob": round(market_prob, 4),
                "agent_id": agent_id,
                "ticker": ticker,
                "bias_range": self.bias_range,
            },
            contributions={
                "market": round(market_prob, 4),
                "hash_bias": round(bias, 4),
            },
            rationale="hash_deterministic_bias",
        )

        raw_confidence = round(0.4 + abs(edge) * 4, 2)
        confidence = self._apply_confidence_clamp(raw_confidence, explanation)

        return OpinionEstimate(
            agent_prob=round(agent_prob, 4),
            confidence=confidence,
            edge=round(edge, 4),
            reasoning_tag="hash_bias",
            signal_sources=["market_implied_prob", "agent_model"],
            explanation=explanation,
        )


class MeanReversionStrategy(OpinionStrategy):
    """Contrarian strategy that fades extreme market probabilities.

    When market_prob is far from 0.5, this strategy nudges the estimate
    back toward the center, betting on mean reversion. Stronger effect
    for more extreme probabilities.
    """

    name = "mean_reversion"

    def __init__(self, reversion_strength: float = 0.15, min_edge: float = 0.02, max_confidence: float = 0.95):
        self.reversion_strength = reversion_strength
        self.min_edge = min_edge
        self.max_confidence = max_confidence

    def estimate(
        self,
        agent_id: str,
        ticker: str,
        market_prob: float,
        category: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[OpinionEstimate]:
        if self.should_skip(market_prob):
            return None

        # Pull toward 0.5 proportional to distance from center
        distance_from_center = market_prob - 0.5
        adjustment = -distance_from_center * self.reversion_strength
        agent_prob = max(0.02, min(0.98, market_prob + adjustment))
        edge = agent_prob - market_prob

        if abs(edge) < self.min_edge:
            return None

        explanation = OpinionExplanation(
            inputs_used={
                "market_prob": round(market_prob, 4),
                "distance_from_center": round(distance_from_center, 4),
                "reversion_strength": self.reversion_strength,
            },
            contributions={
                "market": round(market_prob, 4),
                "mean_reversion": round(adjustment, 4),
            },
            rationale="mean_reversion_pull_toward_0.5"
                      if abs(market_prob - 0.5) > 0.15
                      else "mild_mean_reversion",
        )

        raw_confidence = round(0.3 + abs(edge) * 3, 2)
        confidence = self._apply_confidence_clamp(raw_confidence, explanation)

        return OpinionEstimate(
            agent_prob=round(agent_prob, 4),
            confidence=confidence,
            edge=round(edge, 4),
            reasoning_tag="mean_reversion",
            signal_sources=["market_implied_prob", "mean_reversion_model"],
            explanation=explanation,
        )


class CalibrationAwareStrategy(OpinionStrategy):
    """Strategy that adjusts toward calibrated base rates per category.

    Uses historical base rates (if available) to anchor the estimate,
    blending market price with category-level priors. Falls back to
    hash bias if no calibration data is available.
    """

    name = "calibration_aware"

    # Default category base rates (fraction of YES outcomes historically)
    DEFAULT_BASE_RATES: Dict[str, float] = {
        "macro": 0.45,
        "politics": 0.50,
        "crypto": 0.40,
        "sports": 0.50,
        "weather": 0.50,
        "equities": 0.48,
        "economics": 0.45,
        "finance": 0.47,
        "science": 0.50,
        "entertainment": 0.50,
        "other": 0.50,
    }

    def __init__(
        self,
        blend_weight: float = 0.20,
        base_rates: Optional[Dict[str, float]] = None,
        min_edge: float = 0.02,
        max_confidence: float = 0.95,
    ):
        self.blend_weight = blend_weight  # How much to weight the base rate vs market
        self.base_rates = base_rates or self.DEFAULT_BASE_RATES
        self.min_edge = min_edge
        self.max_confidence = max_confidence

    def estimate(
        self,
        agent_id: str,
        ticker: str,
        market_prob: float,
        category: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[OpinionEstimate]:
        if self.should_skip(market_prob):
            return None

        base_rate = self.base_rates.get(category, 0.50)
        # Blend: (1-w)*market + w*base_rate
        agent_prob = (1 - self.blend_weight) * market_prob + self.blend_weight * base_rate
        agent_prob = max(0.02, min(0.98, agent_prob))
        edge = agent_prob - market_prob

        if abs(edge) < self.min_edge:
            return None

        market_contribution = (1 - self.blend_weight) * market_prob
        base_rate_contribution = self.blend_weight * base_rate

        explanation = OpinionExplanation(
            inputs_used={
                "market_prob": round(market_prob, 4),
                "category": category or "other",
                "category_base_rate": round(base_rate, 4),
                "blend_weight": self.blend_weight,
            },
            contributions={
                "market": round(market_contribution, 4),
                "category_base_rate": round(base_rate_contribution, 4),
            },
            rationale=f"calibration_adjustment_to_{category or 'other'}_base_rate"
                      if abs(base_rate - market_prob) > 0.05
                      else "calibration_minor_adjustment",
        )

        raw_confidence = round(0.35 + abs(edge) * 3.5, 2)
        confidence = self._apply_confidence_clamp(raw_confidence, explanation)

        return OpinionEstimate(
            agent_prob=round(agent_prob, 4),
            confidence=confidence,
            edge=round(edge, 4),
            reasoning_tag=f"calibration_aware({category})",
            signal_sources=["market_implied_prob", "category_base_rate"],
            explanation=explanation,
        )


# ── ML Explanation Adapter (future-proofing) ─────────────────────────

class MLExplanationAdapter:
    """Converts raw ML model attributions into normalized OpinionExplanation.

    Future ML strategies (LSTM, Prophet, gradient-boosted models) produce
    raw explanation artifacts (SHAP values, LIME weights, feature importances).
    This adapter normalizes them into the same OpinionExplanation shape so
    downstream APIs, dashboards, and alerts remain model-agnostic.

    Usage:
        adapter = MLExplanationAdapter()

        # From SHAP values:
        explanation = adapter.from_shap(
            shap_values={"market_prob": 0.12, "volume": -0.03, "days_to_expiry": 0.05},
            base_value=0.5,
            model_name="xgboost_v1",
        )

        # From LIME weights:
        explanation = adapter.from_lime(
            lime_weights=[("market_prob", 0.15), ("category", -0.02)],
            model_name="lstm_v2",
        )

        # From generic feature importances:
        explanation = adapter.from_feature_importances(
            importances={"market_prob": 0.7, "volume": 0.2, "spread": 0.1},
            prediction=0.65,
            model_name="prophet_v1",
        )
    """

    @staticmethod
    def from_shap(
        shap_values: Dict[str, float],
        base_value: float,
        model_name: str = "ml_model",
        extra_inputs: Optional[Dict[str, Any]] = None,
    ) -> OpinionExplanation:
        """Convert SHAP values into OpinionExplanation."""
        inputs = {"base_value": base_value, "model": model_name}
        if extra_inputs:
            inputs.update(extra_inputs)

        # Normalize: top contributors by absolute magnitude
        sorted_features = sorted(shap_values.items(), key=lambda x: abs(x[1]), reverse=True)
        top_feature = sorted_features[0][0] if sorted_features else "unknown"

        return OpinionExplanation(
            inputs_used=inputs,
            contributions=shap_values,
            rationale=f"shap_{top_feature}_dominant",
        )

    @staticmethod
    def from_lime(
        lime_weights: List[tuple],
        model_name: str = "ml_model",
        extra_inputs: Optional[Dict[str, Any]] = None,
    ) -> OpinionExplanation:
        """Convert LIME explanation weights into OpinionExplanation."""
        inputs: Dict[str, Any] = {"model": model_name}
        if extra_inputs:
            inputs.update(extra_inputs)

        contributions = {name: round(weight, 4) for name, weight in lime_weights}
        sorted_features = sorted(lime_weights, key=lambda x: abs(x[1]), reverse=True)
        top_feature = sorted_features[0][0] if sorted_features else "unknown"

        return OpinionExplanation(
            inputs_used=inputs,
            contributions=contributions,
            rationale=f"lime_{top_feature}_dominant",
        )

    @staticmethod
    def from_feature_importances(
        importances: Dict[str, float],
        prediction: float,
        model_name: str = "ml_model",
        extra_inputs: Optional[Dict[str, Any]] = None,
    ) -> OpinionExplanation:
        """Convert generic feature importances into OpinionExplanation."""
        inputs: Dict[str, Any] = {"model": model_name, "prediction": prediction}
        if extra_inputs:
            inputs.update(extra_inputs)

        sorted_features = sorted(importances.items(), key=lambda x: x[1], reverse=True)
        top_feature = sorted_features[0][0] if sorted_features else "unknown"

        return OpinionExplanation(
            inputs_used=inputs,
            contributions=importances,
            rationale=f"ml_{top_feature}_primary_driver",
        )


# ── Debate strategies ────────────────────────────────────────────────

class ChallengerStrategy(OpinionStrategy):
    """Generates a counter-opinion by opposing the proposer's estimate.

    Used in debate protocol: takes the proposer's probability and generates
    a counter-argument that pulls toward the opposite direction. The strength
    of the challenge depends on how extreme the proposer's deviation from
    market is.

    When ``adaptive_strength=True`` (default), the challenge strength is
    scaled by proposer confidence and historical accuracy:
      - Low-confidence proposer → stronger challenge
      - Historically inaccurate proposer (high Brier) → stronger challenge
    Pass ``proposer_historical_brier`` in context to enable accuracy-based
    adaptation (optional; falls back to fixed strength if absent).
    """

    name = "challenger"

    def __init__(
        self,
        challenge_strength: float = 0.60,
        min_edge: float = 0.01,
        adaptive_strength: bool = True,
    ):
        self.challenge_strength = challenge_strength
        self.min_edge = min_edge
        self.adaptive_strength = adaptive_strength

    def _compute_effective_strength(self, ctx: Dict[str, Any]) -> float:
        """Compute effective challenge strength, optionally adaptive."""
        if not self.adaptive_strength:
            return self.challenge_strength

        base = self.challenge_strength
        proposer_conf = ctx.get("proposer_confidence", 0.5)
        proposer_brier = ctx.get("proposer_historical_brier", None)

        # Low confidence → stronger challenge (scale up when conf < 0.5)
        conf_factor = 1.0 + (0.5 - min(proposer_conf, 1.0)) * 0.5

        # Poor historical accuracy → stronger challenge
        brier_factor = 1.0
        if proposer_brier is not None:
            # Brier ranges 0 (perfect) to 1 (worst); scale up for bad scores
            brier_factor = 1.0 + max(0.0, proposer_brier - 0.25) * 1.0

        effective = base * conf_factor * brier_factor
        return max(0.1, min(0.95, effective))

    def estimate(
        self,
        agent_id: str,
        ticker: str,
        market_prob: float,
        category: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[OpinionEstimate]:
        if self.should_skip(market_prob):
            return None

        ctx = context or {}
        proposer_prob = ctx.get("proposer_prob", market_prob)
        proposer_rationale = ctx.get("proposer_rationale", "unknown")

        effective_strength = self._compute_effective_strength(ctx)

        # Challenge: pull back toward market, weighted by effective strength
        deviation = proposer_prob - market_prob
        counter_adjustment = -deviation * effective_strength
        agent_prob = max(0.02, min(0.98, proposer_prob + counter_adjustment))
        edge = agent_prob - market_prob

        if abs(edge) < self.min_edge:
            agent_prob = market_prob
            edge = 0.0

        explanation = OpinionExplanation(
            inputs_used={
                "market_prob": round(market_prob, 4),
                "proposer_prob": round(proposer_prob, 4),
                "proposer_rationale": proposer_rationale,
                "challenge_strength": round(effective_strength, 4),
                "adaptive": self.adaptive_strength,
            },
            contributions={
                "proposer_base": round(proposer_prob, 4),
                "challenge_pull": round(counter_adjustment, 4),
            },
            rationale=f"challenge_against_{proposer_rationale}",
        )

        return OpinionEstimate(
            agent_prob=round(agent_prob, 4),
            confidence=round(0.3 + abs(deviation) * 2, 2),
            edge=round(edge, 4),
            reasoning_tag="challenger",
            signal_sources=["proposer_opinion", "market_implied_prob"],
            explanation=explanation,
        )


class ArbiterStrategy(OpinionStrategy):
    """Synthesizes a revised estimate from proposer and challenger arguments.

    Used as the final round in a debate: takes both opinions and produces
    a confidence-weighted blend, favoring the more confident argument.
    """

    name = "arbiter"

    def __init__(self, min_edge: float = 0.005):
        self.min_edge = min_edge

    def estimate(
        self,
        agent_id: str,
        ticker: str,
        market_prob: float,
        category: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[OpinionEstimate]:
        if self.should_skip(market_prob):
            return None

        ctx = context or {}
        proposer_prob = ctx.get("proposer_prob", market_prob)
        proposer_conf = ctx.get("proposer_confidence", 0.5)
        challenger_prob = ctx.get("challenger_prob", market_prob)
        challenger_conf = ctx.get("challenger_confidence", 0.5)

        # Confidence-weighted blend
        total_conf = proposer_conf + challenger_conf
        if total_conf == 0:
            agent_prob = (proposer_prob + challenger_prob) / 2
        else:
            agent_prob = (proposer_prob * proposer_conf + challenger_prob * challenger_conf) / total_conf

        agent_prob = max(0.02, min(0.98, agent_prob))
        edge = agent_prob - market_prob

        proposer_weight = round(proposer_conf / total_conf, 4) if total_conf > 0 else 0.5
        challenger_weight = round(1.0 - proposer_weight, 4)

        explanation = OpinionExplanation(
            inputs_used={
                "market_prob": round(market_prob, 4),
                "proposer_prob": round(proposer_prob, 4),
                "proposer_confidence": round(proposer_conf, 4),
                "challenger_prob": round(challenger_prob, 4),
                "challenger_confidence": round(challenger_conf, 4),
            },
            contributions={
                "proposer_weighted": round(proposer_prob * proposer_weight, 4),
                "challenger_weighted": round(challenger_prob * challenger_weight, 4),
            },
            rationale="arbiter_confidence_weighted_synthesis",
        )

        return OpinionEstimate(
            agent_prob=round(agent_prob, 4),
            confidence=round(min(0.9, (proposer_conf + challenger_conf) / 2 + 0.1), 2),
            edge=round(edge, 4),
            reasoning_tag="arbiter",
            signal_sources=["proposer_opinion", "challenger_opinion", "market_implied_prob"],
            explanation=explanation,
        )


class BayesianArbiterStrategy(OpinionStrategy):
    """Arbiter that treats proposer and challenger as independent signals.

    Converts each opinion to log-odds, averages the log-odds (equivalent to
    treating them as independent Bayesian updates from a 0.5 prior), then
    converts back to probability. This naturally handles asymmetric confidence
    by weighting more extreme opinions more heavily in log-odds space.
    """

    name = "arbiter_bayesian"

    def __init__(self, min_edge: float = 0.005):
        self.min_edge = min_edge

    def estimate(
        self,
        agent_id: str,
        ticker: str,
        market_prob: float,
        category: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[OpinionEstimate]:
        if self.should_skip(market_prob):
            return None

        ctx = context or {}
        proposer_prob = ctx.get("proposer_prob", market_prob)
        proposer_conf = ctx.get("proposer_confidence", 0.5)
        challenger_prob = ctx.get("challenger_prob", market_prob)
        challenger_conf = ctx.get("challenger_confidence", 0.5)

        # Clamp to avoid log(0)
        p_prop = max(0.01, min(0.99, proposer_prob))
        p_chal = max(0.01, min(0.99, challenger_prob))

        # Convert to log-odds, weight by confidence
        lo_prop = math.log(p_prop / (1 - p_prop)) * proposer_conf
        lo_chal = math.log(p_chal / (1 - p_chal)) * challenger_conf

        # Average weighted log-odds
        total_conf = proposer_conf + challenger_conf
        if total_conf == 0:
            lo_avg = 0.0
        else:
            lo_avg = (lo_prop + lo_chal) / total_conf

        # Convert back to probability
        agent_prob = 1.0 / (1.0 + math.exp(-lo_avg))
        agent_prob = max(0.02, min(0.98, agent_prob))
        edge = agent_prob - market_prob

        explanation = OpinionExplanation(
            inputs_used={
                "market_prob": round(market_prob, 4),
                "proposer_prob": round(proposer_prob, 4),
                "proposer_confidence": round(proposer_conf, 4),
                "challenger_prob": round(challenger_prob, 4),
                "challenger_confidence": round(challenger_conf, 4),
            },
            contributions={
                "proposer_log_odds_weighted": round(lo_prop, 4),
                "challenger_log_odds_weighted": round(lo_chal, 4),
                "combined_log_odds": round(lo_avg, 4),
            },
            rationale="arbiter_bayesian_log_odds_synthesis",
        )

        return OpinionEstimate(
            agent_prob=round(agent_prob, 4),
            confidence=round(min(0.9, (proposer_conf + challenger_conf) / 2 + 0.1), 2),
            edge=round(edge, 4),
            reasoning_tag="arbiter_bayesian",
            signal_sources=["proposer_opinion", "challenger_opinion", "market_implied_prob"],
            explanation=explanation,
        )


class ExtremizingArbiterStrategy(OpinionStrategy):
    """Arbiter that pushes the blended estimate further from 0.5.

    Research on group forecasting shows that simple averages tend to
    under-extremize (the truth is often more extreme than the mean forecast).
    This strategy first computes a confidence-weighted blend, then pushes it
    further from 0.5 by an extremization factor.
    """

    name = "arbiter_extremizing"

    def __init__(self, extremize_factor: float = 1.5, min_edge: float = 0.005):
        self.extremize_factor = extremize_factor  # >1 = push away from 0.5
        self.min_edge = min_edge

    def estimate(
        self,
        agent_id: str,
        ticker: str,
        market_prob: float,
        category: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[OpinionEstimate]:
        if self.should_skip(market_prob):
            return None

        ctx = context or {}
        proposer_prob = ctx.get("proposer_prob", market_prob)
        proposer_conf = ctx.get("proposer_confidence", 0.5)
        challenger_prob = ctx.get("challenger_prob", market_prob)
        challenger_conf = ctx.get("challenger_confidence", 0.5)

        # Step 1: confidence-weighted blend (same as base arbiter)
        total_conf = proposer_conf + challenger_conf
        if total_conf == 0:
            blended = (proposer_prob + challenger_prob) / 2
        else:
            blended = (proposer_prob * proposer_conf + challenger_prob * challenger_conf) / total_conf

        # Step 2: extremize — convert to log-odds, multiply, convert back
        blended_clamped = max(0.01, min(0.99, blended))
        lo = math.log(blended_clamped / (1 - blended_clamped))
        lo_extremized = lo * self.extremize_factor
        agent_prob = 1.0 / (1.0 + math.exp(-lo_extremized))
        agent_prob = max(0.02, min(0.98, agent_prob))
        edge = agent_prob - market_prob

        explanation = OpinionExplanation(
            inputs_used={
                "market_prob": round(market_prob, 4),
                "proposer_prob": round(proposer_prob, 4),
                "challenger_prob": round(challenger_prob, 4),
                "extremize_factor": self.extremize_factor,
            },
            contributions={
                "blended_pre_extremize": round(blended, 4),
                "log_odds_pre": round(lo, 4),
                "log_odds_post": round(lo_extremized, 4),
            },
            rationale="arbiter_extremized_synthesis",
        )

        return OpinionEstimate(
            agent_prob=round(agent_prob, 4),
            confidence=round(min(0.9, (proposer_conf + challenger_conf) / 2 + 0.15), 2),
            edge=round(edge, 4),
            reasoning_tag="arbiter_extremizing",
            signal_sources=["proposer_opinion", "challenger_opinion", "market_implied_prob"],
            explanation=explanation,
        )


class MedianArbiterStrategy(OpinionStrategy):
    """Arbiter that takes the simple midpoint of proposer and challenger.

    Serves as a baseline: no confidence weighting, no extremization.
    Useful for measuring whether more sophisticated arbiters add value.
    """

    name = "arbiter_median"

    def __init__(self, min_edge: float = 0.005):
        self.min_edge = min_edge

    def estimate(
        self,
        agent_id: str,
        ticker: str,
        market_prob: float,
        category: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[OpinionEstimate]:
        if self.should_skip(market_prob):
            return None

        ctx = context or {}
        proposer_prob = ctx.get("proposer_prob", market_prob)
        challenger_prob = ctx.get("challenger_prob", market_prob)

        agent_prob = (proposer_prob + challenger_prob) / 2
        agent_prob = max(0.02, min(0.98, agent_prob))
        edge = agent_prob - market_prob

        explanation = OpinionExplanation(
            inputs_used={
                "market_prob": round(market_prob, 4),
                "proposer_prob": round(proposer_prob, 4),
                "challenger_prob": round(challenger_prob, 4),
            },
            contributions={
                "proposer_half": round(proposer_prob / 2, 4),
                "challenger_half": round(challenger_prob / 2, 4),
            },
            rationale="arbiter_simple_midpoint",
        )

        return OpinionEstimate(
            agent_prob=round(agent_prob, 4),
            confidence=0.4,
            edge=round(edge, 4),
            reasoning_tag="arbiter_median",
            signal_sources=["proposer_opinion", "challenger_opinion"],
            explanation=explanation,
        )


# ── Strategy registry ────────────────────────────────────────────────

_STRATEGIES: Dict[str, type] = {
    "hash_bias": HashBiasStrategy,
    "mean_reversion": MeanReversionStrategy,
    "calibration_aware": CalibrationAwareStrategy,
    "challenger": ChallengerStrategy,
    "arbiter": ArbiterStrategy,
    "arbiter_bayesian": BayesianArbiterStrategy,
    "arbiter_extremizing": ExtremizingArbiterStrategy,
    "arbiter_median": MedianArbiterStrategy,
}


def get_strategy(name: str = "hash_bias", **kwargs) -> OpinionStrategy:
    """Get an opinion strategy by name."""
    cls = _STRATEGIES.get(name)
    if cls is None:
        raise ValueError(f"Unknown opinion strategy: {name}. Available: {list(_STRATEGIES.keys())}")
    return cls(**kwargs)


def register_strategy(name: str, cls: type) -> None:
    """Register a custom opinion strategy."""
    _STRATEGIES[name] = cls


def list_strategies() -> List[str]:
    """List available strategy names."""
    return list(_STRATEGIES.keys())
