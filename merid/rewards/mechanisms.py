"""Reward Mechanisms — pluggable scoring rules applied by the RewardEngine.

Each mechanism receives a RewardEvent and returns zero or more point awards.
Mechanisms are config-driven: decay rates, multipliers, caps, and thresholds
are all tunable without code changes.

Mechanism types:
  AccuracyMechanism     — Brier-based scoring for forecasts
  ImprovementMechanism  — rewards Brier/calibration deltas (antifragile)
  ExplanationMechanism  — rewards structured explanations with rationale
  StabilityMechanism    — rewards system improvements (tests, SLOs, alerts)
  InsightMechanism      — rewards useful disagreements and hypothesis updates
"""

from __future__ import annotations

import threading
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from merid.rewards.events import (
    RewardEvent,
    ForecastEvent,
    DebateEvent,
    CognitiveEvent,
    CodeQualityEvent,
    DevForecastEvent,
    DevDebateEvent,
    EventCategory,
)
from utils.logger import get_logger

logger = get_logger("merid.rewards.mechanisms")


# ── Mechanism output ──────────────────────────────────────────────────

@dataclass
class PointAward:
    """A single point award produced by a mechanism."""
    reward_type: str = ""        # e.g. "accuracy", "improvement", "insight"
    points: float = 0.0
    detail: str = ""
    category: str = ""           # maps to EventCategory for distribution tracking
    mechanism_name: str = ""     # which mechanism produced this


# ── Base mechanism ────────────────────────────────────────────────────

class RewardMechanism:
    """Abstract base for reward mechanisms.

    Subclasses implement `evaluate(event) -> List[PointAward]`.
    Config is passed at construction and can be updated at runtime.
    """

    name: str = "base"
    description: str = ""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def evaluate(self, event: RewardEvent) -> List[PointAward]:
        """Evaluate an event and return zero or more point awards."""
        raise NotImplementedError

    def applies_to(self, event: RewardEvent) -> bool:
        """Return True if this mechanism should process this event."""
        return True


# ── Accuracy mechanism ────────────────────────────────────────────────

class AccuracyMechanism(RewardMechanism):
    """Brier-based scoring for forecast and dev-forecast events.

    Config keys:
      base_points      — points for submitting any forecast (default 10.0)
      brier_bonus_max  — max bonus for perfect Brier (default 50.0)
      brier_threshold  — Brier below which bonus kicks in (default 1.0)
    """

    name = "accuracy"
    description = "Brier-based accuracy rewards for forecasts"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.base_points = self.config.get("base_points", 10.0)
        self.brier_bonus_max = self.config.get("brier_bonus_max", 50.0)
        self.brier_threshold = self.config.get("brier_threshold", 1.0)

    def applies_to(self, event: RewardEvent) -> bool:
        return event.category in (
            EventCategory.FORECAST.value,
            EventCategory.DEV_FORECAST.value,
        )

    def evaluate(self, event: RewardEvent) -> List[PointAward]:
        awards: List[PointAward] = []

        # Base timeliness points
        awards.append(PointAward(
            reward_type="timeliness",
            points=self.base_points,
            detail="Timely forecast submitted",
            category=event.category,
            mechanism_name=self.name,
        ))

        # Brier-based accuracy bonus
        brier = getattr(event, "brier_score", None)
        if brier is not None and brier < self.brier_threshold:
            bonus = round(self.brier_bonus_max * (1.0 - brier), 2)
            if bonus > 0:
                awards.append(PointAward(
                    reward_type="accuracy",
                    points=bonus,
                    detail=f"Brier={brier:.4f}, bonus={bonus:.2f}",
                    category=event.category,
                    mechanism_name=self.name,
                ))

        return awards


# ── Improvement mechanism (antifragile) ───────────────────────────────

class ImprovementMechanism(RewardMechanism):
    """Rewards improvement over prior performance, not just raw accuracy.

    This is the core antifragile mechanism: agents earn more when they
    *learn from errors* and improve their Brier/calibration over time.

    Config keys:
      improvement_bonus_max  — max bonus for large improvement (default 40.0)
      anchoring_penalty      — penalty for worsening Brier (default -5.0)
      min_improvement        — minimum delta to trigger bonus (default 0.01)
    """

    name = "improvement"
    description = "Rewards Brier/calibration improvement over prior performance"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.improvement_bonus_max = self.config.get("improvement_bonus_max", 40.0)
        self.anchoring_penalty = self.config.get("anchoring_penalty", -5.0)
        self.min_improvement = self.config.get("min_improvement", 0.01)

    def applies_to(self, event: RewardEvent) -> bool:
        return event.category in (
            EventCategory.FORECAST.value,
            EventCategory.DEV_FORECAST.value,
        )

    def evaluate(self, event: RewardEvent) -> List[PointAward]:
        awards: List[PointAward] = []
        brier = getattr(event, "brier_score", None)
        prior = getattr(event, "prior_brier", None)

        if brier is None or prior is None:
            return awards

        delta = prior - brier  # positive = improved

        if delta >= self.min_improvement:
            # Scale bonus: larger improvement = more points, capped
            scale = min(delta / 0.25, 1.0)  # normalize to 0.25 Brier improvement
            bonus = round(self.improvement_bonus_max * scale, 2)
            awards.append(PointAward(
                reward_type="improvement",
                points=bonus,
                detail=f"Brier improved by {delta:.4f} (prior={prior:.4f}, now={brier:.4f})",
                category=event.category,
                mechanism_name=self.name,
            ))
        elif delta < -self.min_improvement:
            # Anti-anchoring: small penalty for getting worse
            awards.append(PointAward(
                reward_type="anchoring_penalty",
                points=self.anchoring_penalty,
                detail=f"Brier worsened by {abs(delta):.4f} (prior={prior:.4f}, now={brier:.4f})",
                category=event.category,
                mechanism_name=self.name,
            ))

        return awards


# ── Explanation mechanism ─────────────────────────────────────────────

class ExplanationMechanism(RewardMechanism):
    """Rewards structured explanations with non-empty rationale.

    Config keys:
      explanation_bonus  — points for providing explanation (default 5.0)
      require_rationale  — require non-empty rationale string (default True)
    """

    name = "explanation"
    description = "Rewards structured explanations attached to events"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.explanation_bonus = self.config.get("explanation_bonus", 5.0)
        self.require_rationale = self.config.get("require_rationale", True)

    def applies_to(self, event: RewardEvent) -> bool:
        return event.category in (
            EventCategory.FORECAST.value,
            EventCategory.DEBATE.value,
        )

    def evaluate(self, event: RewardEvent) -> List[PointAward]:
        has_explanation = getattr(event, "has_explanation", False)
        rationale = getattr(event, "explanation_rationale", "")

        if not has_explanation:
            return []

        if self.require_rationale and not rationale.strip():
            return []

        return [PointAward(
            reward_type="explanation",
            points=self.explanation_bonus,
            detail="Structured explanation provided",
            category=event.category,
            mechanism_name=self.name,
        )]


# ── Stability mechanism ──────────────────────────────────────────────

class StabilityMechanism(RewardMechanism):
    """Rewards system-improvement actions: tests, SLOs, alert reductions.

    Config keys:
      points_per_test     — points per test added (default 3.0)
      points_per_alert    — points per alert reduced (default 5.0)
      slo_improvement_max — max bonus for SLO improvement (default 20.0)
      bug_fix_bonus       — points for fixing a bug (default 10.0)
    """

    name = "stability"
    description = "Rewards system improvements (tests, SLOs, alerts)"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.points_per_test = self.config.get("points_per_test", 3.0)
        self.points_per_alert = self.config.get("points_per_alert", 5.0)
        self.slo_improvement_max = self.config.get("slo_improvement_max", 20.0)
        self.bug_fix_bonus = self.config.get("bug_fix_bonus", 10.0)

    def applies_to(self, event: RewardEvent) -> bool:
        return event.category == EventCategory.CODE_QUALITY.value

    def evaluate(self, event: RewardEvent) -> List[PointAward]:
        awards: List[PointAward] = []

        tests_added = getattr(event, "tests_added", 0)
        alerts_reduced = getattr(event, "alerts_reduced", 0)
        action = getattr(event, "action", "")
        impact_before = getattr(event, "impact_before", None)
        impact_after = getattr(event, "impact_after", None)

        if tests_added > 0:
            pts = round(self.points_per_test * tests_added, 2)
            awards.append(PointAward(
                reward_type="stability_tests",
                points=pts,
                detail=f"{tests_added} tests added",
                category=event.category,
                mechanism_name=self.name,
            ))

        if alerts_reduced > 0:
            pts = round(self.points_per_alert * alerts_reduced, 2)
            awards.append(PointAward(
                reward_type="stability_alerts",
                points=pts,
                detail=f"{alerts_reduced} alerts reduced",
                category=event.category,
                mechanism_name=self.name,
            ))

        if action == "bug_fixed":
            awards.append(PointAward(
                reward_type="stability_bugfix",
                points=self.bug_fix_bonus,
                detail="Bug fix shipped",
                category=event.category,
                mechanism_name=self.name,
            ))

        if action == "slo_tightened" and impact_before is not None and impact_after is not None:
            # Reward proportional to improvement
            if impact_after < impact_before:
                improvement_pct = (impact_before - impact_after) / max(impact_before, 0.001)
                pts = round(self.slo_improvement_max * min(improvement_pct, 1.0), 2)
                if pts > 0:
                    awards.append(PointAward(
                        reward_type="stability_slo",
                        points=pts,
                        detail=f"SLO improved: {impact_before:.2f} → {impact_after:.2f}",
                        category=event.category,
                        mechanism_name=self.name,
                    ))

        return awards


# ── Insight mechanism ─────────────────────────────────────────────────

class InsightMechanism(RewardMechanism):
    """Rewards useful disagreements, debate lift, and hypothesis updates.

    Config keys:
      debate_lift_bonus_max    — max bonus for positive debate lift (default 30.0)
      min_disagreement         — min disagreement width for lift bonus (default 0.03)
      hypothesis_update_bonus  — points for updating a hypothesis (default 8.0)
      contradiction_bonus      — extra points when updating after contradiction (default 12.0)
      design_lift_bonus_max    — max bonus for positive design debate lift (default 25.0)
    """

    name = "insight"
    description = "Rewards useful disagreements, debate lift, and hypothesis updates"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.debate_lift_bonus_max = self.config.get("debate_lift_bonus_max", 30.0)
        self.min_disagreement = self.config.get("min_disagreement", 0.03)
        self.hypothesis_update_bonus = self.config.get("hypothesis_update_bonus", 8.0)
        self.contradiction_bonus = self.config.get("contradiction_bonus", 12.0)
        self.design_lift_bonus_max = self.config.get("design_lift_bonus_max", 25.0)

    def applies_to(self, event: RewardEvent) -> bool:
        return event.category in (
            EventCategory.DEBATE.value,
            EventCategory.COGNITIVE.value,
            EventCategory.DEV_DEBATE.value,
        )

    def evaluate(self, event: RewardEvent) -> List[PointAward]:
        awards: List[PointAward] = []

        if event.category == EventCategory.DEBATE.value:
            awards.extend(self._evaluate_debate(event))
        elif event.category == EventCategory.COGNITIVE.value:
            awards.extend(self._evaluate_cognitive(event))
        elif event.category == EventCategory.DEV_DEBATE.value:
            awards.extend(self._evaluate_dev_debate(event))

        return awards

    def _evaluate_debate(self, event: RewardEvent) -> List[PointAward]:
        awards: List[PointAward] = []
        lift = getattr(event, "debate_lift", None)
        disagreement = getattr(event, "disagreement_width", 0.0)
        suppressed = getattr(event, "was_suppressed", False)

        if suppressed:
            return awards

        if lift is not None and lift > 0 and disagreement >= self.min_disagreement:
            bonus = round(self.debate_lift_bonus_max * min(lift * 4, 1.0), 2)
            awards.append(PointAward(
                reward_type="debate_lift",
                points=bonus,
                detail=f"Debate lift={lift:.4f}, disagreement={disagreement:.4f}",
                category=event.category,
                mechanism_name=self.name,
            ))

        return awards

    def _evaluate_cognitive(self, event: RewardEvent) -> List[PointAward]:
        awards: List[PointAward] = []
        action = getattr(event, "action", "")
        was_contradicted = getattr(event, "was_contradicted", False)

        if action in ("updated", "retired"):
            pts = self.hypothesis_update_bonus
            detail = f"Hypothesis {action}"

            if was_contradicted:
                pts += self.contradiction_bonus
                detail += " after reality contradiction (antifragile update)"

            awards.append(PointAward(
                reward_type="insight_hypothesis",
                points=pts,
                detail=detail,
                category=event.category,
                mechanism_name=self.name,
            ))

        return awards

    def _evaluate_dev_debate(self, event: RewardEvent) -> List[PointAward]:
        awards: List[PointAward] = []
        lift = getattr(event, "design_lift", None)
        disagreement = getattr(event, "disagreement_width", 0.0)

        if lift is not None and lift > 0 and disagreement >= self.min_disagreement:
            bonus = round(self.design_lift_bonus_max * min(lift * 4, 1.0), 2)
            awards.append(PointAward(
                reward_type="design_lift",
                points=bonus,
                detail=f"Design debate lift={lift:.4f}",
                category=event.category,
                mechanism_name=self.name,
            ))

        return awards


# ── Mechanism registry ────────────────────────────────────────────────

class MechanismRegistry:
    """Central registry of all active reward mechanisms.

    Mechanisms are evaluated in registration order.  The registry can be
    reconfigured at runtime to tune incentives.
    """

    def __init__(self) -> None:
        self._mechanisms: List[RewardMechanism] = []

    def register(self, mechanism: RewardMechanism) -> None:
        self._mechanisms.append(mechanism)

    def unregister(self, name: str) -> None:
        self._mechanisms = [m for m in self._mechanisms if m.name != name]

    def get(self, name: str) -> Optional[RewardMechanism]:
        for m in self._mechanisms:
            if m.name == name:
                return m
        return None

    def list_mechanisms(self) -> List[str]:
        return [m.name for m in self._mechanisms]

    def evaluate_all(self, event: RewardEvent) -> List[PointAward]:
        """Run all applicable mechanisms against an event."""
        awards: List[PointAward] = []
        for mechanism in self._mechanisms:
            if mechanism.applies_to(event):
                try:
                    awards.extend(mechanism.evaluate(event))
                except Exception as exc:
                    logger.warning("Mechanism %s failed on event %s: %s",
                                   mechanism.name, event.id, exc)
        return awards

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mechanisms": [
                {"name": m.name, "description": m.description, "config": m.config}
                for m in self._mechanisms
            ],
            "count": len(self._mechanisms),
        }


# ── Default registry singleton ────────────────────────────────────────

_DEFAULT_REGISTRY: Optional[MechanismRegistry] = None
_DEFAULT_REGISTRY_lock = threading.Lock()


def get_mechanism_registry() -> MechanismRegistry:
    """Get or create the default mechanism registry with all built-in mechanisms."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        with _DEFAULT_REGISTRY_lock:
            if _DEFAULT_REGISTRY is None:
                _DEFAULT_REGISTRY = MechanismRegistry()
                _DEFAULT_REGISTRY.register(AccuracyMechanism())
                _DEFAULT_REGISTRY.register(ImprovementMechanism())
                _DEFAULT_REGISTRY.register(ExplanationMechanism())
                _DEFAULT_REGISTRY.register(StabilityMechanism())
                _DEFAULT_REGISTRY.register(InsightMechanism())
    return _DEFAULT_REGISTRY
