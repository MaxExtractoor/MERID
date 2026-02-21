"""Reality Debugger — detects stuck models, conceptual disagreement, and hypothesis dynamics.

This is the "observability for world-models" layer.  It answers:
  - "What story are we implicitly assuming here?"
  - "Where did that story fail, and who updated (or didn't) when reality contradicted it?"

Core analyses:
  StuckModel             — high error but hypotheses haven't changed since a surprise
  ConceptualDisagreement — agents with similar probs but different underlying hypotheses
  HypothesisDynamics     — flip rate, update lag after surprise, rigidity detection
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.logger import get_logger

from merid.cognitive.models import (
    CognitiveSnapshot,
    Hypothesis,
    HypothesisAction,
    HypothesisStatus,
)

logger = get_logger("merid.cognitive.reality_debugger")


# ── Result dataclasses ────────────────────────────────────────────────

@dataclass
class StuckModel:
    """A market where hypotheses haven't updated despite a surprise/error."""
    market_id: str = ""
    brier_score: float = 0.0         # current forecast error
    last_hypothesis_update: float = 0.0  # epoch of most recent hypothesis change
    surprise_at: float = 0.0         # when the surprise/resolution happened
    lag_seconds: float = 0.0         # time since surprise with no update
    stale_hypotheses: int = 0        # count of unchanged hypotheses
    owners: List[str] = field(default_factory=list)
    suggestion: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "brier_score": round(self.brier_score, 4),
            "last_hypothesis_update": self.last_hypothesis_update,
            "surprise_at": self.surprise_at,
            "lag_seconds": round(self.lag_seconds, 1),
            "stale_hypotheses": self.stale_hypotheses,
            "owners": self.owners,
            "suggestion": self.suggestion,
        }


@dataclass
class ConceptualDisagreement:
    """Agents with similar probabilities but different underlying hypotheses."""
    market_id: str = ""
    agents: List[Dict[str, Any]] = field(default_factory=list)
    probability_spread: float = 0.0  # how close their probs are
    regime_tags_a: List[str] = field(default_factory=list)
    regime_tags_b: List[str] = field(default_factory=list)
    suggestion: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "agents": self.agents,
            "probability_spread": round(self.probability_spread, 4),
            "regime_tags_a": self.regime_tags_a,
            "regime_tags_b": self.regime_tags_b,
            "suggestion": self.suggestion,
        }


@dataclass
class HypothesisDynamics:
    """Dynamics of hypothesis changes over a time window."""
    market_id: str = ""
    window_seconds: float = 604800.0
    total_actions: int = 0
    flips: int = 0                   # broken + created in quick succession
    updates: int = 0
    creations: int = 0
    retirements: int = 0
    breakages: int = 0
    flip_rate_per_day: float = 0.0
    mean_lag_after_surprise_s: Optional[float] = None
    rigidity_flag: bool = False      # too few updates
    flailing_flag: bool = False      # too many flips with no improvement

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "window_seconds": self.window_seconds,
            "total_actions": self.total_actions,
            "flips": self.flips,
            "updates": self.updates,
            "creations": self.creations,
            "retirements": self.retirements,
            "breakages": self.breakages,
            "flip_rate_per_day": round(self.flip_rate_per_day, 3),
            "mean_lag_after_surprise_s": (
                round(self.mean_lag_after_surprise_s, 1)
                if self.mean_lag_after_surprise_s is not None else None
            ),
            "rigidity_flag": self.rigidity_flag,
            "flailing_flag": self.flailing_flag,
        }


# ── Reality Debugger ──────────────────────────────────────────────────

class RealityDebugger:
    """Analyzes cognitive health across markets and agents.

    Uses a CognitiveStore to detect:
      - Stuck models (high error, stale hypotheses)
      - Conceptual disagreement (same probs, different stories)
      - Hypothesis dynamics (flip rate, lag, rigidity)

    Config thresholds:
      brier_threshold      — Brier score above which a model is "surprised" (default 0.4)
      stale_lag_s          — seconds after surprise with no update → stuck (default 3 days)
      prob_spread_threshold — max prob difference for "similar" probs (default 0.10)
      flip_rate_high       — flips/day above which → flailing (default 2.0)
      flip_rate_low        — flips/day below which → rigid (default 0.05)
      min_actions_for_flailing — minimum actions to flag flailing (default 5)
    """

    def __init__(
        self,
        store=None,
        brier_threshold: float = 0.4,
        stale_lag_s: float = 259200.0,    # 3 days
        prob_spread_threshold: float = 0.10,
        flip_rate_high: float = 2.0,
        flip_rate_low: float = 0.05,
        min_actions_for_flailing: int = 5,
    ):
        self._store = store
        self.brier_threshold = brier_threshold
        self.stale_lag_s = stale_lag_s
        self.prob_spread_threshold = prob_spread_threshold
        self.flip_rate_high = flip_rate_high
        self.flip_rate_low = flip_rate_low
        self.min_actions_for_flailing = min_actions_for_flailing

    @property
    def store(self):
        if self._store is None:
            from merid.cognitive.store import get_cognitive_store
            self._store = get_cognitive_store()
        return self._store

    # ── Stuck model detection ─────────────────────────────────────────

    def detect_stuck_models(
        self,
        market_brier_scores: Dict[str, float],
        market_surprise_times: Optional[Dict[str, float]] = None,
    ) -> List[StuckModel]:
        """Find markets with high Brier error and stale hypotheses.

        Args:
            market_brier_scores: {market_id: brier_score} for recently resolved/scored markets
            market_surprise_times: {market_id: epoch} when the surprise happened (optional,
                                   defaults to current time minus stale_lag_s)
        """
        if market_surprise_times is None:
            market_surprise_times = {}

        stuck = []
        now = time.time()

        for market_id, brier in market_brier_scores.items():
            if brier < self.brier_threshold:
                continue

            surprise_at = market_surprise_times.get(market_id, now)
            hypotheses = self.store.get_active_hypotheses_for_market(market_id)

            if not hypotheses:
                # No hypotheses at all — also a problem
                stuck.append(StuckModel(
                    market_id=market_id,
                    brier_score=brier,
                    last_hypothesis_update=0.0,
                    surprise_at=surprise_at,
                    lag_seconds=now - surprise_at,
                    stale_hypotheses=0,
                    owners=[],
                    suggestion="No hypotheses exist for this market despite high error. "
                               "Consider creating a cognitive snapshot.",
                ))
                continue

            latest_update = max(h.updated_at for h in hypotheses)
            lag = now - max(latest_update, surprise_at)

            # Count hypotheses not updated since the surprise
            stale_count = sum(1 for h in hypotheses if h.updated_at < surprise_at)
            owners = list(set(h.owner for h in hypotheses if h.owner))

            if stale_count > 0 and lag > self.stale_lag_s:
                stuck.append(StuckModel(
                    market_id=market_id,
                    brier_score=brier,
                    last_hypothesis_update=latest_update,
                    surprise_at=surprise_at,
                    lag_seconds=lag,
                    stale_hypotheses=stale_count,
                    owners=owners,
                    suggestion=f"{stale_count} hypothesis(es) unchanged since surprise. "
                               f"Owners {owners} should review assumptions.",
                ))

        return stuck

    # ── Conceptual disagreement ───────────────────────────────────────

    def detect_conceptual_disagreements(
        self,
        market_id: str,
        agent_probabilities: Dict[str, float],
    ) -> List[ConceptualDisagreement]:
        """Find agents with similar probabilities but different hypotheses.

        Args:
            market_id: the market to analyze
            agent_probabilities: {agent_id: probability} for current forecasts
        """
        disagreements = []
        agents = list(agent_probabilities.keys())

        # Get hypotheses per agent for this market
        all_hyps = self.store.get_active_hypotheses_for_market(market_id)
        hyps_by_owner: Dict[str, List[Hypothesis]] = {}
        for h in all_hyps:
            hyps_by_owner.setdefault(h.owner, []).append(h)

        # Compare all pairs
        for i in range(len(agents)):
            for j in range(i + 1, len(agents)):
                a, b = agents[i], agents[j]
                prob_a = agent_probabilities[a]
                prob_b = agent_probabilities[b]
                spread = abs(prob_a - prob_b)

                if spread > self.prob_spread_threshold:
                    continue  # probs are too different — not a hidden disagreement

                tags_a = set(
                    h.regime_tag.label for h in hyps_by_owner.get(a, [])
                    if h.regime_tag.label
                )
                tags_b = set(
                    h.regime_tag.label for h in hyps_by_owner.get(b, [])
                    if h.regime_tag.label
                )

                if not tags_a or not tags_b:
                    continue  # need tags from both to detect disagreement

                overlap = tags_a & tags_b
                if len(overlap) < min(len(tags_a), len(tags_b)):
                    disagreements.append(ConceptualDisagreement(
                        market_id=market_id,
                        agents=[
                            {"agent_id": a, "probability": round(prob_a, 4)},
                            {"agent_id": b, "probability": round(prob_b, 4)},
                        ],
                        probability_spread=spread,
                        regime_tags_a=sorted(tags_a),
                        regime_tags_b=sorted(tags_b),
                        suggestion=f"Agents {a} and {b} have similar probs "
                                   f"({prob_a:.2f} vs {prob_b:.2f}) but different regime tags. "
                                   f"Investigate underlying assumptions.",
                    ))

        return disagreements

    # ── Hypothesis dynamics ───────────────────────────────────────────

    def compute_hypothesis_dynamics(
        self,
        market_id: str,
        window_s: float = 604800.0,
        surprise_times: Optional[List[float]] = None,
    ) -> HypothesisDynamics:
        """Compute hypothesis change dynamics for a market.

        Args:
            market_id: the market to analyze
            window_s: time window in seconds (default 7 days)
            surprise_times: list of epoch times when surprises occurred
        """
        actions = self.store.get_actions_for_market(market_id, window_s=window_s)

        creations = sum(1 for a in actions if a["action"] == HypothesisAction.CREATED.value)
        updates = sum(
            1 for a in actions
            if a["action"] in (
                HypothesisAction.UPDATED.value,
                HypothesisAction.CONFIDENCE_ADJUSTED.value,
            )
        )
        breakages = sum(1 for a in actions if a["action"] == HypothesisAction.BROKEN.value)
        retirements = sum(1 for a in actions if a["action"] == HypothesisAction.RETIRED.value)

        # Flips = broken followed by creation within 24h
        flips = 0
        broken_times = sorted(
            a["created_at"] for a in actions
            if a["action"] == HypothesisAction.BROKEN.value
        )
        creation_times = sorted(
            a["created_at"] for a in actions
            if a["action"] == HypothesisAction.CREATED.value
        )
        for bt in broken_times:
            for ct in creation_times:
                if 0 < (ct - bt) < 86400:  # creation within 24h of breakage
                    flips += 1
                    break

        days = window_s / 86400.0
        flip_rate = flips / days if days > 0 else 0.0

        # Compute mean lag after surprise
        mean_lag: Optional[float] = None
        if surprise_times:
            lags = []
            for st in surprise_times:
                # Find first action after this surprise
                post_surprise = [
                    a["created_at"] for a in actions
                    if a["created_at"] > st and a["action"] in (
                        HypothesisAction.BROKEN.value,
                        HypothesisAction.UPDATED.value,
                        HypothesisAction.CONFIDENCE_ADJUSTED.value,
                    )
                ]
                if post_surprise:
                    lags.append(min(post_surprise) - st)
            if lags:
                mean_lag = sum(lags) / len(lags)

        total = len(actions)
        rigidity = total < 2 and days >= 7  # almost no activity in a week
        flailing = (
            flip_rate > self.flip_rate_high
            and total >= self.min_actions_for_flailing
        )

        return HypothesisDynamics(
            market_id=market_id,
            window_seconds=window_s,
            total_actions=total,
            flips=flips,
            updates=updates,
            creations=creations,
            retirements=retirements,
            breakages=breakages,
            flip_rate_per_day=flip_rate,
            mean_lag_after_surprise_s=mean_lag,
            rigidity_flag=rigidity,
            flailing_flag=flailing,
        )

    # ── Full reality debug report ─────────────────────────────────────

    def reality_debug(
        self,
        market_brier_scores: Optional[Dict[str, float]] = None,
        market_surprise_times: Optional[Dict[str, float]] = None,
        agent_probabilities: Optional[Dict[str, Dict[str, float]]] = None,
        window_s: float = 604800.0,
    ) -> Dict[str, Any]:
        """Generate a full reality debug report.

        Args:
            market_brier_scores: {market_id: brier} for scored markets
            market_surprise_times: {market_id: epoch} when surprises happened
            agent_probabilities: {market_id: {agent_id: prob}} for current forecasts
            window_s: time window for dynamics analysis
        """
        if market_brier_scores is None:
            market_brier_scores = {}
        if agent_probabilities is None:
            agent_probabilities = {}

        # Stuck models
        stuck = self.detect_stuck_models(market_brier_scores, market_surprise_times)

        # Conceptual disagreements
        disagreements = []
        for market_id, probs in agent_probabilities.items():
            disagreements.extend(
                self.detect_conceptual_disagreements(market_id, probs)
            )

        # Hypothesis dynamics for all markets with activity
        all_markets: Set[str] = set(market_brier_scores.keys()) | set(agent_probabilities.keys())
        dynamics = {}
        for mid in all_markets:
            surprise_list = (
                [market_surprise_times[mid]]
                if market_surprise_times and mid in market_surprise_times
                else None
            )
            dynamics[mid] = self.compute_hypothesis_dynamics(
                mid, window_s=window_s, surprise_times=surprise_list,
            ).to_dict()

        # Cognitive metrics from store
        metrics = self.store.get_cognitive_metrics(window_s=window_s)

        return {
            "stuck_models": [s.to_dict() for s in stuck],
            "conceptual_disagreements": [d.to_dict() for d in disagreements],
            "hypothesis_dynamics": dynamics,
            "cognitive_metrics": metrics,
            "markets_analyzed": len(all_markets),
            "stuck_count": len(stuck),
            "disagreement_count": len(disagreements),
        }

    # ── Cognitive health metrics for observability ─────────────────────

    def get_cognitive_health(
        self,
        market_brier_scores: Optional[Dict[str, float]] = None,
        market_surprise_times: Optional[Dict[str, float]] = None,
        window_s: float = 604800.0,
    ) -> Dict[str, Any]:
        """Compute cognitive health metrics for the observability endpoint.

        Returns:
            Dict with:
              - pct_surprised_with_updates: % of surprised markets that got hypothesis updates
              - mean_hypothesis_lag_after_surprise: average lag in seconds
              - hypothesis_flip_rate: flips per day across all markets
              - active_hypotheses: count
              - broken_hypotheses: count
              - rigidity_count: markets flagged as rigid
              - flailing_count: markets flagged as flailing
        """
        if market_brier_scores is None:
            market_brier_scores = {}
        if market_surprise_times is None:
            market_surprise_times = {}

        metrics = self.store.get_cognitive_metrics(window_s=window_s)

        # Compute per-market dynamics for surprised markets
        surprised_markets = {
            mid: brier for mid, brier in market_brier_scores.items()
            if brier >= self.brier_threshold
        }

        updated_count = 0
        total_surprised = len(surprised_markets)
        lags: List[float] = []
        total_flips = 0
        rigidity_count = 0
        flailing_count = 0

        all_markets_with_hyps = set()
        actions = self.store.get_all_actions(window_s=window_s)
        for a in actions:
            if a.get("market_id"):
                all_markets_with_hyps.add(a["market_id"])

        for mid in all_markets_with_hyps | set(surprised_markets.keys()):
            surprise_list = (
                [market_surprise_times[mid]]
                if mid in market_surprise_times
                else None
            )
            dyn = self.compute_hypothesis_dynamics(
                mid, window_s=window_s, surprise_times=surprise_list,
            )
            total_flips += dyn.flips
            if dyn.rigidity_flag:
                rigidity_count += 1
            if dyn.flailing_flag:
                flailing_count += 1

            if mid in surprised_markets:
                if dyn.total_actions > 0:
                    updated_count += 1
                if dyn.mean_lag_after_surprise_s is not None:
                    lags.append(dyn.mean_lag_after_surprise_s)

        days = window_s / 86400.0
        n_markets = max(len(all_markets_with_hyps), 1)

        return {
            "pct_surprised_with_updates": (
                round(100.0 * updated_count / total_surprised, 1)
                if total_surprised > 0 else 100.0
            ),
            "mean_hypothesis_lag_after_surprise_s": (
                round(sum(lags) / len(lags), 1) if lags else None
            ),
            "hypothesis_flip_rate_per_day": round(total_flips / days, 3) if days > 0 else 0.0,
            "active_hypotheses": metrics.get("active_hypotheses", 0),
            "broken_hypotheses": metrics.get("broken_hypotheses", 0),
            "total_hypotheses": metrics.get("total_hypotheses", 0),
            "markets_covered": metrics.get("markets_covered", 0),
            "unique_owners": metrics.get("unique_owners", 0),
            "rigidity_count": rigidity_count,
            "flailing_count": flailing_count,
            "window_seconds": window_s,
        }


# ── Singleton ─────────────────────────────────────────────────────────

_DEBUGGER: Optional[RealityDebugger] = None
_DEBUGGER_LOCK = threading.Lock()


def get_reality_debugger() -> RealityDebugger:
    """Get or create the global RealityDebugger singleton."""
    global _DEBUGGER
    if _DEBUGGER is None:
        with _DEBUGGER_LOCK:
            if _DEBUGGER is None:
                _DEBUGGER = RealityDebugger()
    return _DEBUGGER
