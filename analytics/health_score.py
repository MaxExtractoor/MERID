"""Customer health score and churn risk helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PaymentStatus = Literal["current", "delinquent", "unpaid"]


@dataclass(frozen=True)
class UsageSignal:
    active_features: int
    total_features: int
    weekly_actions: int


@dataclass(frozen=True)
class SentimentSignal:
    nps: float  # -100 to 100
    csat: float  # 1-5 scale


@dataclass(frozen=True)
class FinancialSignal:
    arr_commit_usd: float
    payment_status: PaymentStatus


@dataclass(frozen=True)
class HealthScoreWeights:
    usage: float
    sentiment: float
    financial: float


@dataclass(frozen=True)
class RiskIncident:
    flagged: bool
    reason: str


@dataclass(frozen=True)
class ChurnRisk:
    probability: float
    incident: RiskIncident


class InteractionFeaturesMissing(RuntimeError):
    """Raised when interaction signals are unavailable for risk scoring."""


def _bounded(value: float, *, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _usage_score(signal: UsageSignal) -> float:
    feature_ratio = _bounded(signal.active_features / max(signal.total_features, 1))
    actions_ratio = _bounded(signal.weekly_actions / 500.0)
    return 0.6 * feature_ratio + 0.4 * actions_ratio


def _sentiment_score(signal: SentimentSignal) -> float:
    nps_score = _bounded((signal.nps + 100) / 200)
    csat_score = _bounded((signal.csat - 1) / 4)
    return 0.5 * nps_score + 0.5 * csat_score


def _financial_score(signal: FinancialSignal) -> float:
    commitment_score = _bounded(signal.arr_commit_usd / 1_000_000)
    status_penalty = {"current": 1.0, "delinquent": 0.5, "unpaid": 0.1}[signal.payment_status]
    return _bounded(commitment_score * status_penalty)


def compute_health_score(
    usage: UsageSignal,
    sentiment: SentimentSignal,
    financial: FinancialSignal,
    *,
    weights: HealthScoreWeights,
) -> float:
    """Blend usage, sentiment, and financial signals into a 0-1 score."""

    total = weights.usage + weights.sentiment + weights.financial
    if total <= 0:
        raise ValueError("Weights must be positive")
    u = _usage_score(usage)
    s = _sentiment_score(sentiment)
    f = _financial_score(financial)
    return _bounded((weights.usage * u + weights.sentiment * s + weights.financial * f) / total)


def compute_churn_risk(
    usage: UsageSignal,
    sentiment: SentimentSignal,
    financial: FinancialSignal,
    *,
    interaction_features: bool,
    weights: HealthScoreWeights,
) -> ChurnRisk:
    """Return churn probability and risk incident data."""

    if not interaction_features:
        raise InteractionFeaturesMissing("Interaction feature set missing for churn risk")

    score = compute_health_score(usage, sentiment, financial, weights=weights)
    payment_penalty = 0.25 if financial.payment_status != "current" else 0.0
    low_usage_penalty = 0.2 if usage.weekly_actions < 100 else 0.0
    low_sentiment_penalty = 0.2 if sentiment.nps < 0 or sentiment.csat < 3 else 0.0

    probability = _bounded(1 - score + payment_penalty + low_usage_penalty + low_sentiment_penalty)
    reason_parts = []
    if payment_penalty:
        reason_parts.append("payment")
    if low_usage_penalty:
        reason_parts.append("usage")
    if low_sentiment_penalty:
        reason_parts.append("sentiment")
    if score < 0.3:
        reason_parts.append("low_health")

    incident = RiskIncident(flagged=probability > 0.6, reason="_".join(reason_parts) or "stable")
    return ChurnRisk(probability=probability, incident=incident)
