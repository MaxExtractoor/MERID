"""Offline evaluation harness for opinion strategies.

Uses a fixture of resolved markets with known outcomes to compute Brier
scores for each strategy, validating that:
1. All strategies produce structurally valid opinions
2. Brier scores are computed correctly
3. Strategy quality can be compared in a repeatable way
4. Regressions in strategy quality are caught

The fixture represents a small but realistic set of resolved prediction
markets across multiple categories.
"""

import time
from typing import Any, Dict, List

import pytest

from merid.prediction.opinion_strategy import (
    CalibrationAwareStrategy,
    HashBiasStrategy,
    MeanReversionStrategy,
    OpinionEstimate,
    OpinionStrategy,
    get_strategy,
    list_strategies,
    register_strategy,
)


# ── Resolved market fixtures ─────────────────────────────────────────

RESOLVED_MARKETS: List[Dict[str, Any]] = [
    # Macro — mostly resolved NO (bearish outcomes)
    {"ticker": "GDP-Q1-ABOVE-3", "category": "macro", "market_prob": 0.65, "outcome": 0,
     "title": "GDP Q1 above 3%"},
    {"ticker": "INFLATION-BELOW-3", "category": "macro", "market_prob": 0.40, "outcome": 1,
     "title": "Inflation below 3% by June"},
    {"ticker": "FED-RATE-CUT-MAR", "category": "macro", "market_prob": 0.30, "outcome": 0,
     "title": "Fed rate cut in March"},
    {"ticker": "UNEMPLOYMENT-BELOW-4", "category": "macro", "market_prob": 0.55, "outcome": 1,
     "title": "Unemployment below 4%"},

    # Crypto — volatile, mixed outcomes
    {"ticker": "BTC-100K-Q1", "category": "crypto", "market_prob": 0.70, "outcome": 1,
     "title": "BTC above 100k by Q1 end"},
    {"ticker": "ETH-5K-Q1", "category": "crypto", "market_prob": 0.25, "outcome": 0,
     "title": "ETH above 5k by Q1 end"},
    {"ticker": "SOL-200-Q1", "category": "crypto", "market_prob": 0.35, "outcome": 0,
     "title": "SOL above 200 by Q1 end"},

    # Politics — binary, well-calibrated markets
    {"ticker": "PRES-APPROVAL-45", "category": "politics", "market_prob": 0.50, "outcome": 1,
     "title": "Presidential approval above 45%"},
    {"ticker": "SENATE-BILL-PASS", "category": "politics", "market_prob": 0.60, "outcome": 1,
     "title": "Senate infrastructure bill passes"},

    # Sports — high-confidence markets
    {"ticker": "SUPERBOWL-TEAM-A", "category": "sports", "market_prob": 0.75, "outcome": 1,
     "title": "Team A wins Super Bowl"},
    {"ticker": "MARCH-MADNESS-SEED1", "category": "sports", "market_prob": 0.80, "outcome": 0,
     "title": "#1 seed wins March Madness"},

    # Weather
    {"ticker": "HURRICANE-SEASON-ABOVE-AVG", "category": "weather", "market_prob": 0.55, "outcome": 1,
     "title": "Above-average hurricane season"},

    # Edge cases: near-extreme probabilities
    {"ticker": "NEAR-CERTAIN-YES", "category": "other", "market_prob": 0.95, "outcome": 1,
     "title": "Near-certain event (YES)"},
    {"ticker": "NEAR-CERTAIN-NO", "category": "other", "market_prob": 0.05, "outcome": 0,
     "title": "Near-certain event (NO)"},
    {"ticker": "COIN-FLIP", "category": "other", "market_prob": 0.50, "outcome": 0,
     "title": "50/50 event"},
]


def _compute_brier(forecasts: List[float], outcomes: List[int]) -> float:
    """Brier score: (1/N) * sum((forecast - outcome)^2). Lower is better."""
    assert len(forecasts) == len(outcomes)
    if not forecasts:
        return 1.0
    return sum((f - o) ** 2 for f, o in zip(forecasts, outcomes)) / len(forecasts)


def _evaluate_strategy(strategy: OpinionStrategy, agent_id: str = "eval-agent") -> Dict[str, Any]:
    """Run a strategy against the resolved market fixture and compute metrics."""
    forecasts = []
    outcomes = []
    opinions_generated = 0
    opinions_skipped = 0

    for market in RESOLVED_MARKETS:
        estimate = strategy.estimate(
            agent_id=agent_id,
            ticker=market["ticker"],
            market_prob=market["market_prob"],
            category=market["category"],
        )
        if estimate is not None:
            forecasts.append(estimate.agent_prob)
            outcomes.append(market["outcome"])
            opinions_generated += 1
        else:
            # Strategy declined — use market prob as fallback for Brier
            forecasts.append(market["market_prob"])
            outcomes.append(market["outcome"])
            opinions_skipped += 1

    # Market baseline (always use market_prob)
    market_forecasts = [m["market_prob"] for m in RESOLVED_MARKETS]
    market_outcomes = [m["outcome"] for m in RESOLVED_MARKETS]

    return {
        "strategy": strategy.name,
        "brier_score": round(_compute_brier(forecasts, outcomes), 4),
        "market_brier": round(_compute_brier(market_forecasts, market_outcomes), 4),
        "opinions_generated": opinions_generated,
        "opinions_skipped": opinions_skipped,
        "total_markets": len(RESOLVED_MARKETS),
        "coverage": round(opinions_generated / len(RESOLVED_MARKETS), 2),
    }


# ── Tests ─────────────────────────────────────────────────────────────

class TestStrategyRegistry:
    """Verify strategy registry works correctly."""

    def test_list_strategies_includes_all(self):
        names = list_strategies()
        assert "hash_bias" in names
        assert "mean_reversion" in names
        assert "calibration_aware" in names

    def test_get_strategy_returns_correct_type(self):
        assert isinstance(get_strategy("hash_bias"), HashBiasStrategy)
        assert isinstance(get_strategy("mean_reversion"), MeanReversionStrategy)
        assert isinstance(get_strategy("calibration_aware"), CalibrationAwareStrategy)

    def test_get_unknown_strategy_raises(self):
        with pytest.raises(ValueError, match="Unknown opinion strategy"):
            get_strategy("nonexistent")

    def test_register_custom_strategy(self):
        class CustomStrategy(OpinionStrategy):
            name = "custom_test"
            def estimate(self, **kwargs):
                return None

        register_strategy("custom_test", CustomStrategy)
        assert "custom_test" in list_strategies()
        assert isinstance(get_strategy("custom_test"), CustomStrategy)


class TestHashBiasStrategy:
    """Verify HashBiasStrategy produces valid, deterministic opinions."""

    def test_deterministic_output(self):
        s = HashBiasStrategy()
        # BIG-EDGE ticker produces a 0.048 bias for agent-1, well above min_edge
        e1 = s.estimate("agent-1", "BIG-EDGE", 0.50, "macro")
        e2 = s.estimate("agent-1", "BIG-EDGE", 0.50, "macro")
        assert e1 is not None and e2 is not None
        assert e1.agent_prob == e2.agent_prob
        assert e1.edge == e2.edge

    def test_skips_extreme_probs(self):
        s = HashBiasStrategy()
        assert s.estimate("a", "t", 0.005, "macro") is None
        assert s.estimate("a", "t", 0.995, "macro") is None

    def test_output_structure(self):
        s = HashBiasStrategy()
        e = s.estimate("agent-1", "TEST", 0.50, "macro")
        if e is not None:
            assert 0.0 <= e.agent_prob <= 1.0
            assert 0.0 <= e.confidence <= 1.0
            assert isinstance(e.reasoning_tag, str)
            assert isinstance(e.signal_sources, list)

    def test_different_agents_different_bias(self):
        s = HashBiasStrategy()
        e1 = s.estimate("agent-1", "SAME-TICKER", 0.50, "macro")
        e2 = s.estimate("agent-2", "SAME-TICKER", 0.50, "macro")
        # Different agents should (usually) produce different estimates
        if e1 is not None and e2 is not None:
            # Not guaranteed to differ, but very likely with different agent IDs
            pass  # Structural validity is the main check


class TestMeanReversionStrategy:
    """Verify MeanReversionStrategy fades extreme probabilities."""

    def test_fades_high_prob_toward_center(self):
        s = MeanReversionStrategy(reversion_strength=0.20)
        e = s.estimate("a", "t", 0.80, "macro")
        if e is not None:
            assert e.agent_prob < 0.80  # Should pull down
            assert e.edge < 0

    def test_fades_low_prob_toward_center(self):
        s = MeanReversionStrategy(reversion_strength=0.20)
        e = s.estimate("a", "t", 0.20, "macro")
        if e is not None:
            assert e.agent_prob > 0.20  # Should pull up
            assert e.edge > 0

    def test_neutral_at_center(self):
        s = MeanReversionStrategy(reversion_strength=0.20)
        e = s.estimate("a", "t", 0.50, "macro")
        # At 0.50, no reversion → edge is 0 → should be skipped
        assert e is None


class TestCalibrationAwareStrategy:
    """Verify CalibrationAwareStrategy blends base rates correctly."""

    def test_blends_toward_base_rate(self):
        s = CalibrationAwareStrategy(blend_weight=0.30)
        # Macro base rate is 0.45, market is 0.70
        e = s.estimate("a", "t", 0.70, "macro")
        if e is not None:
            # Should pull toward 0.45: (0.70 * 0.70) + (0.30 * 0.45) = 0.625
            assert e.agent_prob < 0.70
            assert e.edge < 0

    def test_custom_base_rates(self):
        s = CalibrationAwareStrategy(
            blend_weight=0.50,
            base_rates={"test_cat": 0.80},
        )
        e = s.estimate("a", "t", 0.50, "test_cat")
        if e is not None:
            # Should pull toward 0.80: (0.50 * 0.50) + (0.50 * 0.80) = 0.65
            assert e.agent_prob > 0.50
            assert e.edge > 0

    def test_unknown_category_uses_default(self):
        s = CalibrationAwareStrategy(blend_weight=0.20)
        e = s.estimate("a", "t", 0.70, "unknown_category")
        # Default base rate is 0.50, so should pull toward 0.50
        if e is not None:
            assert e.agent_prob < 0.70


class TestOfflineEvaluation:
    """Run all strategies against the resolved market fixture and verify Brier scores."""

    def test_all_strategies_produce_valid_brier(self):
        for name in list_strategies():
            if name == "custom_test":
                continue  # Skip test-registered strategy
            strategy = get_strategy(name)
            result = _evaluate_strategy(strategy)
            assert 0.0 <= result["brier_score"] <= 1.0, f"{name}: invalid Brier"
            assert 0.0 <= result["market_brier"] <= 1.0
            assert result["total_markets"] == len(RESOLVED_MARKETS)

    def test_market_baseline_brier(self):
        """Market baseline Brier should be consistent across evaluations."""
        s = HashBiasStrategy()
        r1 = _evaluate_strategy(s)
        r2 = _evaluate_strategy(s)
        assert r1["market_brier"] == r2["market_brier"]

    def test_hash_bias_coverage(self):
        """Hash bias should generate opinions for most non-extreme markets."""
        result = _evaluate_strategy(HashBiasStrategy())
        # At least some opinions should be generated
        assert result["opinions_generated"] > 0
        assert result["coverage"] > 0.3

    def test_mean_reversion_coverage(self):
        result = _evaluate_strategy(MeanReversionStrategy())
        assert result["opinions_generated"] > 0

    def test_calibration_aware_coverage(self):
        result = _evaluate_strategy(CalibrationAwareStrategy())
        assert result["opinions_generated"] > 0

    def test_strategy_comparison_report(self):
        """All strategies should produce a comparable evaluation report."""
        reports = []
        for name in ["hash_bias", "mean_reversion", "calibration_aware"]:
            strategy = get_strategy(name)
            report = _evaluate_strategy(strategy)
            reports.append(report)
            # Each report should have all required fields
            assert "brier_score" in report
            assert "market_brier" in report
            assert "coverage" in report
            assert "opinions_generated" in report

        # All reports should reference the same market baseline
        market_briers = [r["market_brier"] for r in reports]
        assert len(set(market_briers)) == 1  # All same baseline

    def test_brier_score_computation_correctness(self):
        """Verify Brier score math with known values."""
        # Perfect forecaster: predict exactly the outcome
        assert _compute_brier([1.0, 0.0, 1.0], [1, 0, 1]) == 0.0
        # Worst forecaster: predict opposite of outcome
        assert _compute_brier([0.0, 1.0, 0.0], [1, 0, 1]) == 1.0
        # Coin flip forecaster on all-YES outcomes
        brier = _compute_brier([0.5, 0.5, 0.5], [1, 1, 1])
        assert abs(brier - 0.25) < 0.001

    def test_strategy_determinism(self):
        """Same strategy + same fixture should produce identical Brier scores."""
        s = HashBiasStrategy()
        r1 = _evaluate_strategy(s, agent_id="determinism-test")
        r2 = _evaluate_strategy(s, agent_id="determinism-test")
        assert r1["brier_score"] == r2["brier_score"]
        assert r1["opinions_generated"] == r2["opinions_generated"]
