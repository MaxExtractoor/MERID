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


class HashBiasStrategy(OpinionStrategy):
    """Deterministic hash-based bias strategy (baseline).

    Generates a repeatable ±5% bias from agent_id + ticker, producing
    structurally valid opinions that prove the pipeline works. Not intended
    to be accurate — serves as the default until a calibrated model is available.
    """

    name = "hash_bias"

    def __init__(self, bias_range: float = 0.10, min_edge: float = 0.02):
        self.bias_range = bias_range  # Total range (±half)
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

        return OpinionEstimate(
            agent_prob=round(agent_prob, 4),
            confidence=round(0.4 + abs(edge) * 4, 2),
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

    def __init__(self, reversion_strength: float = 0.15, min_edge: float = 0.02):
        self.reversion_strength = reversion_strength
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

        return OpinionEstimate(
            agent_prob=round(agent_prob, 4),
            confidence=round(0.3 + abs(edge) * 3, 2),
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
    ):
        self.blend_weight = blend_weight  # How much to weight the base rate vs market
        self.base_rates = base_rates or self.DEFAULT_BASE_RATES
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

        return OpinionEstimate(
            agent_prob=round(agent_prob, 4),
            confidence=round(0.35 + abs(edge) * 3.5, 2),
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


class KalshiLiveMarketStrategy(OpinionStrategy):
    """Market-data-driven opinion strategy using live Kalshi orderbook signals.

    Synthesizes probability estimates from:
      1. Order book imbalance (depth-weighted bid/ask ratio)
      2. Spread tightness (lower spread → more confident)
      3. Expiry damping (markets near expiry get lower confidence)
      4. Volume/liquidity signals

    Fallback: when no live state is available, uses sentiment_score from context
    (if provided) to generate a basic opinion.

    Parameters:
        imbalance_weight (float): How much imbalance contributes to edge (default 0.05)
        spread_weight (float): How much tight spread contributes (default 0.02)
        min_edge (float): Minimum edge to emit opinion (default 0.005)
    """

    name = "kalshi_live_market"

    SENTIMENT_WEIGHT: float = 0.03  # 3% cap on sentiment contribution

    def __init__(
        self,
        imbalance_weight: float = 0.05,
        spread_weight: float = 0.02,
        min_edge: float = 0.001,
    ):
        self.imbalance_weight = imbalance_weight
        self.spread_weight = spread_weight
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
        sentiment_score = ctx.get("sentiment_score")

        try:
            from merid.event_venues.kalshi.market_state import (
                get_kalshi_market_state_store,
            )

            state = get_kalshi_market_state_store().get(ticker)
        except Exception:
            state = None

        if state is None:
            # Fallback: use sentiment_score if available
            return self._fallback_estimate(agent_id, ticker, market_prob, ctx)

        # Live market data path
        if not getattr(state, "book_initialized", False):
            return self._fallback_estimate(agent_id, ticker, market_prob, ctx)

        # Extract orderbook signals
        try:
            mid_cents = float(getattr(state, "mid_cents", 0) or 0)
            spread_cents = float(getattr(state, "spread_cents", 0) or 0)
            yes_bids = getattr(state, "yes_bids", []) or []
            no_bids = getattr(state, "no_bids", []) or []

            # O-C1 FIX: Preserve seconds_to_expiry=0 (expired), don't coerce to 7*86400
            _ste_raw = getattr(state, "seconds_to_expiry", None)
            seconds_to_expiry = _ste_raw if _ste_raw is not None else 7 * 86400

        except (AttributeError, TypeError, ValueError):
            return self._fallback_estimate(agent_id, ticker, market_prob, ctx)

        # Compute imbalance signal from yes/no bid depths
        yes_depth = sum(size for _, size in yes_bids) if yes_bids else 0
        no_depth = sum(size for _, size in no_bids) if no_bids else 0
        total_depth = yes_depth + no_depth

        imbalance_bias = 0.0
        if total_depth > 0:
            imbalance_ratio = yes_depth / total_depth if total_depth > 0 else 0.5
            # Imbalance pulls prob toward 1.0 if yes_depth > no_depth, toward 0.0 otherwise
            imbalance_deviation = imbalance_ratio - 0.5
            imbalance_bias = self.imbalance_weight * imbalance_deviation  # max ±0.05

        # Compute spread signal (tight spread = higher confidence)
        # Normalize spread to fractional impact: spread_cents / 100 (price range)
        spread_factor = 1.0 - min(1.0, spread_cents / 4.0) if spread_cents >= 0 else 1.0

        # Compute expiry damping: near-expiry markets get lower weight
        # seconds_to_expiry=0 → expiry_scale=0.25 (dampened)
        # seconds_to_expiry>3600 (>1h) → expiry_scale=1.0 (full)
        if seconds_to_expiry <= 0:
            expiry_scale = 0.25
        elif seconds_to_expiry <= 3600:
            # Linear ramp from 0.25 to 1.0 between 0 and 3600 seconds
            expiry_scale = 0.25 + (seconds_to_expiry / 3600.0) * 0.75
        else:
            expiry_scale = 1.0

        # Compute base probability from mid_cents if available, else market_prob
        base_prob = mid_cents / 100.0 if mid_cents > 0 else market_prob

        # Combine signals: imbalance + spread, scaled by expiry
        combined_bias = (imbalance_bias * spread_factor) * expiry_scale

        # Apply limits
        agent_prob = max(0.02, min(0.98, base_prob + combined_bias))
        edge = agent_prob - market_prob

        # Filter by min_edge - return None if below threshold (respects per-instance min_edge)
        if abs(edge) < self.min_edge:
            return None

        # Build signal sources using canonical taxonomy
        try:
            from merid.event_venues.kalshi.invariants import KalshiSignalSource
            signal_sources = KalshiSignalSource.live_market_sources()
            if sentiment_score is not None:
                signal_sources.append(KalshiSignalSource.NEWS_SENTIMENT)
            # Validate sources are canonical
            KalshiSignalSource.validate_sources(signal_sources, context="KalshiLiveMarketStrategy")
        except Exception:
            # Fallback to string literals if invariants not available
            signal_sources = ["kalshi_orderbook", "kalshi_spread", "kalshi_expiry"]
            if sentiment_score is not None:
                signal_sources.append("news_sentiment")
        explanation = OpinionExplanation(
            inputs_used={
                "market_prob": round(market_prob, 4),
                "ticker": ticker,
                "yes_depth": yes_depth,
                "no_depth": no_depth,
                "spread_cents": round(spread_cents, 2),
                "seconds_to_expiry": seconds_to_expiry,
                "imbalance_weight": self.imbalance_weight,
                "spread_weight": self.spread_weight,
                "imbalance_raw": imbalance_bias,
                "mid_cents": mid_cents,
            },
            contributions={
                "market": round(market_prob, 4),
                "base_prob": round(base_prob, 4),
                "book_imbalance": round(imbalance_bias, 4),
                "imbalance_bias": round(imbalance_bias, 4),
                "spread_effect": round((spread_factor - 1.0) * imbalance_bias, 4),
                "expiry_damping": round((expiry_scale - 1.0) * combined_bias, 4),
            },
            rationale=f"kalshi_live_market_primary",
        )

        return OpinionEstimate(
            agent_prob=round(agent_prob, 4),
            confidence=round(
                0.4 + abs(edge) * 2 + (spread_factor * 0.2), 2
            ),  # spread + edge → higher confidence
            edge=round(edge, 4),
            reasoning_tag="kalshi_live_market",
            signal_sources=signal_sources,
            explanation=explanation,
        )

    def _fallback_estimate(
        self, agent_id: str, ticker: str, market_prob: float, ctx: Dict[str, Any]
    ) -> Optional[OpinionEstimate]:
        """Fallback when live market data is unavailable.

        Uses sentiment_score from context if available. Produces a distinct
        reasoning_tag so callers can identify fallback vs live signals.
        """
        sentiment_score = ctx.get("sentiment_score", None)
        if sentiment_score is None:
            return None

        # sentiment_score should be in [-1, 1]; convert to probability adjustment
        # sentiment_score=0.5 → +0.03 edge (capped by SENTIMENT_WEIGHT), sentiment_score=-0.5 → -0.03 edge
        sentiment_bias = (sentiment_score or 0.0) * self.SENTIMENT_WEIGHT

        agent_prob = max(0.02, min(0.98, market_prob + sentiment_bias))
        edge = agent_prob - market_prob

        if abs(edge) < self.min_edge:
            return None

        explanation = OpinionExplanation(
            inputs_used={
                "market_prob": round(market_prob, 4),
                "sentiment_score": round(sentiment_score, 4),
                "min_edge": self.min_edge,
            },
            contributions={
                "market": round(market_prob, 4),
                "sentiment_bias": round(sentiment_bias, 4),
            },
            rationale="kalshi_market_prob_fallback",
        )

        return OpinionEstimate(
            agent_prob=round(agent_prob, 4),
            confidence=round(0.3 + abs(edge) * 1.5, 2),
            edge=round(edge, 4),
            reasoning_tag="kalshi_market_prob_fallback",
            signal_sources=["news_sentiment"],
            explanation=explanation,
        )


class SpotBasisFairValueStrategy(OpinionStrategy):
    """Strategy A: log-normal fair value from CryptoTermStructureModel + orderbook overlay.

    Covers BTC/ETH/SOL/XRP/DOGE across all Kalshi crypto timeframes.
    Returns None during TSM warm-up (is_ready=False) so other strategies stay active.
    """

    name = "spot_basis_fair_value"

    def __init__(
        self,
        imbalance_weight: float = 0.03,
        min_edge: float = 0.02,
    ) -> None:
        self.imbalance_weight = imbalance_weight
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
        asset: str = ctx.get("asset", "")
        horizon_secs: float = float(ctx.get("horizon_secs", 3_600.0))
        market_type: str = ctx.get("market_type", "")

        if not asset or not market_type:
            return None

        try:
            from merid.risk.crypto_term_structure import get_global_crypto_tsm
            tsm = get_global_crypto_tsm()
        except Exception:
            return None

        if not tsm.is_ready(asset):
            return None

        # ── compute model probability ─────────────────────────────────────────
        if market_type == "up_down":
            p_model = tsm.up_prob(asset, horizon_secs)
        elif market_type == "threshold":
            strike = ctx.get("strike")
            if strike is None:
                return None
            side = ctx.get("side", "above")
            p_model = tsm.fair_prob(asset, horizon_secs, float(strike), side)
        elif market_type == "bracket":
            bracket = ctx.get("bracket")
            if bracket is None:
                return None
            low, high = bracket
            p_model = tsm.bracket_prob(asset, horizon_secs, float(low), float(high))
        else:
            return None

        # ── orderbook overlay for short horizons (≤ 1h) ──────────────────────
        tsm_prob = p_model  # capture before overlay
        overlay_fired = False
        if horizon_secs <= 3_600:
            try:
                from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                state = get_kalshi_market_state_store().get(ticker)
                if state and getattr(state, "book_initialized", False):
                    yes_depth = sum(s for _, s in (getattr(state, "yes_bids", []) or []))
                    no_depth = sum(s for _, s in (getattr(state, "no_bids", []) or []))
                    total = yes_depth + no_depth
                    if total > 0:
                        imbalance_bias = (yes_depth / total - 0.5) * self.imbalance_weight
                        p_model += imbalance_bias
                        overlay_fired = True
            except Exception:
                pass

        # ── single terminal clamp ─────────────────────────────────────────────
        p_model = max(1e-4, min(1 - 1e-4, p_model))

        edge = p_model - market_prob
        if abs(edge) < self.min_edge:
            return None

        signal_sources = ["rti_term_structure", "log_normal_cdf"]
        if overlay_fired:
            signal_sources.append("orderbook_imbalance")

        explanation = OpinionExplanation(
            inputs_used={
                "asset": asset,
                "horizon_secs": horizon_secs,
                "market_type": market_type,
            },
            contributions={
                "tsm_prob": round(tsm_prob, 4),
                "imbalance_bias": round(p_model - tsm_prob, 4),
            },
            rationale=f"tsm_{market_type}_{asset}",
        )

        return OpinionEstimate(
            agent_prob=round(p_model, 4),
            confidence=round(min(0.85, 0.40 + abs(edge) * 3.0), 2),
            edge=round(edge, 4),
            reasoning_tag="spot_basis_fair_value",
            signal_sources=signal_sources,
            explanation=explanation,
        )


class TrendMomentumOpinionStrategy(OpinionStrategy):
    """Strategy C: MA-cross + momentum from TSM minute-bar history.

    Horizon-adaptive window selection covers all Kalshi crypto timeframes.
    Returns None until sufficient bar history is accumulated.
    """

    name = "trend_momentum"

    # Horizon → (short_bars, long_bars) window pairs
    _WINDOWS = [
        (15 * 60,      5,    30),   # ≤ 15m
        (1 * 3_600,   15,    60),   # ≤ 1h
        (24 * 3_600,  60,   480),   # ≤ 1d
        (float("inf"), 480, 4_320), # weekly / monthly / annual
    ]

    def __init__(
        self,
        short_window: int = 5,       # placeholder; overridden per-horizon internally
        long_window: int = 30,       # placeholder; overridden per-horizon internally
        min_edge: float = 0.02,
        max_signal_strength: float = 0.15,
    ) -> None:
        self.min_edge = min_edge
        self.max_signal_strength = max_signal_strength

    def _resolve_windows(self, horizon_secs: float):
        for limit, short_w, long_w in self._WINDOWS:
            if horizon_secs <= limit:
                return short_w, long_w
        return 480, 4_320  # fallback (unreachable)

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
        asset: str = ctx.get("asset", "")
        horizon_secs: float = float(ctx.get("horizon_secs", 3_600.0))
        market_type: str = ctx.get("market_type", "")

        if not asset or not market_type:
            return None

        try:
            from merid.risk.crypto_term_structure import get_global_crypto_tsm
            tsm = get_global_crypto_tsm()
        except Exception:
            return None

        if not tsm.is_ready(asset):
            return None

        short_w, long_w = self._resolve_windows(horizon_secs)

        # Readiness gate: need long_w bars of returns
        if len(tsm.get_returns(asset, long_w)) < long_w:
            return None

        prices = tsm.get_recent_prices(asset, long_w + 5)
        if len(prices) < long_w:
            return None

        # ── signal computation ────────────────────────────────────────────────
        short_ma = sum(prices[-short_w:]) / short_w
        long_ma = sum(prices[-long_w:]) / long_w
        ma_cross = (short_ma - long_ma) / long_ma if long_ma > 0 else 0.0

        short_returns = tsm.get_returns(asset, short_w)
        momentum = sum(short_returns) / len(short_returns) if short_returns else 0.0

        raw_signal = ma_cross * 0.6 + momentum * 0.4
        signal = max(-self.max_signal_strength, min(self.max_signal_strength, raw_signal))

        # ── tsm_base for non-Up/Down markets ─────────────────────────────────
        if market_type == "up_down":
            tsm_base = 0.5
        elif market_type == "threshold":
            strike = ctx.get("strike")
            if strike is None:
                return None
            side = ctx.get("side", "above")
            tsm_base = (tsm.fair_prob(asset, horizon_secs, float(strike), side)
                        if tsm.is_ready(asset) else market_prob)
        elif market_type == "bracket":
            bracket = ctx.get("bracket")
            if bracket is None:
                return None
            low, high = bracket
            tsm_base = (tsm.bracket_prob(asset, horizon_secs, float(low), float(high))
                        if tsm.is_ready(asset) else market_prob)
        else:
            return None

        # ── single terminal clamp ─────────────────────────────────────────────
        p_model = max(1e-4, min(1 - 1e-4, tsm_base + signal))

        edge = p_model - market_prob
        if abs(edge) < self.min_edge:
            return None

        direction = "bullish" if signal > 0 else "bearish"

        explanation = OpinionExplanation(
            inputs_used={
                "asset": asset,
                "horizon_secs": horizon_secs,
                "short_w": short_w,
                "long_w": long_w,
            },
            contributions={
                "ma_cross": round(ma_cross, 6),
                "momentum": round(momentum, 6),
                "signal": round(signal, 4),
            },
            rationale=f"trend_momentum_{direction}_{asset}",
        )

        return OpinionEstimate(
            agent_prob=round(p_model, 4),
            confidence=round(min(0.80, 0.35 + abs(signal) * 3.0), 2),
            edge=round(edge, 4),
            reasoning_tag=f"trend_momentum_{direction}",
            signal_sources=["ma_cross", "momentum", "rti_minute_bars"],
            explanation=explanation,
        )


# ── Strategy registry ────────────────────────────────────────────────

_STRATEGIES: Dict[str, type] = {
    "hash_bias": HashBiasStrategy,
    "mean_reversion": MeanReversionStrategy,
    "calibration_aware": CalibrationAwareStrategy,
    "kalshi_live_market": KalshiLiveMarketStrategy,
    "challenger": ChallengerStrategy,
    "arbiter": ArbiterStrategy,
    "arbiter_bayesian": BayesianArbiterStrategy,
    "arbiter_extremizing": ExtremizingArbiterStrategy,
    "arbiter_median": MedianArbiterStrategy,
    "spot_basis_fair_value": SpotBasisFairValueStrategy,
    "trend_momentum": TrendMomentumOpinionStrategy,
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
