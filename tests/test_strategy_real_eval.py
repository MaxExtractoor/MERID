"""Real-data strategy evaluation — runs all OpinionStrategies against Kalshi seed
contracts with simulated resolutions and compares Brier scores.

Uses the actual SEED_CONTRACTS from merid/prediction_seed.py as the instrument
universe, assigns plausible resolutions based on market-implied probabilities,
and evaluates each strategy's forecasting quality.

This is the bridge between "strategies produce valid opinions" (unit tests)
and "strategies produce *useful* opinions" (offline evaluation with real data).
"""

import hashlib
import random
import time
from typing import Any, Dict, List, Tuple

import pytest

from merid.prediction.opinion_strategy import (
    CalibrationAwareStrategy,
    HashBiasStrategy,
    MeanReversionStrategy,
    OpinionEstimate,
    OpinionStrategy,
    get_strategy,
    list_strategies,
)
from merid.prediction_seed import SEED_CONTRACTS, SeedContract


# ── Resolution simulation ─────────────────────────────────────────────

def _simulate_resolutions(
    contracts: List[SeedContract],
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """Simulate plausible resolutions for seed contracts.

    Uses the market-implied probability as the true base rate, then draws
    a Bernoulli outcome. This means a contract with implied_prob=0.70 has
    a 70% chance of resolving YES — which is the correct null hypothesis
    for evaluating whether a strategy can beat the market.

    A fixed seed ensures deterministic, reproducible results.
    """
    rng = random.Random(seed)
    resolved = []
    for sc in contracts:
        outcome = 1 if rng.random() < sc.implied_prob else 0
        resolved.append({
            "ticker": sc.id,
            "category": sc.category,
            "market_prob": sc.implied_prob,
            "outcome": outcome,
            "title": sc.question,
        })
    return resolved


def _compute_brier(forecasts: List[float], outcomes: List[int]) -> float:
    """Brier score: (1/N) * sum((forecast - outcome)^2). Lower is better."""
    if not forecasts:
        return 1.0
    return sum((f - o) ** 2 for f, o in zip(forecasts, outcomes)) / len(forecasts)


def _evaluate_strategy_on_resolved(
    strategy: OpinionStrategy,
    resolved: List[Dict[str, Any]],
    agent_id: str = "eval-agent",
) -> Dict[str, Any]:
    """Run a strategy against resolved markets and compute Brier score.

    When the strategy declines to opine (returns None), the market probability
    is used as the fallback forecast — this means a strategy that never opines
    will exactly match the market baseline.
    """
    forecasts = []
    outcomes = []
    opinions_generated = 0
    opinions_skipped = 0
    by_category: Dict[str, Dict[str, List]] = {}

    for market in resolved:
        estimate = strategy.estimate(
            agent_id=agent_id,
            ticker=market["ticker"],
            market_prob=market["market_prob"],
            category=market["category"],
        )

        if estimate is not None:
            forecast = estimate.agent_prob
            opinions_generated += 1
        else:
            forecast = market["market_prob"]
            opinions_skipped += 1

        forecasts.append(forecast)
        outcomes.append(market["outcome"])

        cat = market["category"]
        if cat not in by_category:
            by_category[cat] = {"forecasts": [], "outcomes": [], "market_probs": []}
        by_category[cat]["forecasts"].append(forecast)
        by_category[cat]["outcomes"].append(market["outcome"])
        by_category[cat]["market_probs"].append(market["market_prob"])

    # Market baseline
    market_forecasts = [m["market_prob"] for m in resolved]
    market_outcomes = [m["outcome"] for m in resolved]

    # Per-category Brier
    category_brier = {}
    for cat, data in by_category.items():
        category_brier[cat] = {
            "strategy_brier": round(_compute_brier(data["forecasts"], data["outcomes"]), 4),
            "market_brier": round(_compute_brier(data["market_probs"], data["outcomes"]), 4),
            "count": len(data["forecasts"]),
        }

    strategy_brier = round(_compute_brier(forecasts, outcomes), 4)
    market_brier = round(_compute_brier(market_forecasts, market_outcomes), 4)

    return {
        "strategy": strategy.name,
        "brier_score": strategy_brier,
        "market_brier": market_brier,
        "delta": round(strategy_brier - market_brier, 4),
        "beats_market": strategy_brier < market_brier,
        "opinions_generated": opinions_generated,
        "opinions_skipped": opinions_skipped,
        "total_markets": len(resolved),
        "coverage": round(opinions_generated / len(resolved), 2) if resolved else 0,
        "by_category": category_brier,
    }


# ── Tests ─────────────────────────────────────────────────────────────

class TestResolutionSimulation:
    """Verify resolution simulation is deterministic and plausible."""

    def test_deterministic_with_same_seed(self):
        r1 = _simulate_resolutions(SEED_CONTRACTS, seed=42)
        r2 = _simulate_resolutions(SEED_CONTRACTS, seed=42)
        assert r1 == r2

    def test_different_seeds_produce_different_outcomes(self):
        r1 = _simulate_resolutions(SEED_CONTRACTS, seed=42)
        r2 = _simulate_resolutions(SEED_CONTRACTS, seed=99)
        outcomes1 = [r["outcome"] for r in r1]
        outcomes2 = [r["outcome"] for r in r2]
        assert outcomes1 != outcomes2

    def test_all_contracts_resolved(self):
        resolved = _simulate_resolutions(SEED_CONTRACTS)
        assert len(resolved) == len(SEED_CONTRACTS)
        for r in resolved:
            assert r["outcome"] in (0, 1)
            assert 0.0 < r["market_prob"] < 1.0

    def test_resolution_uses_seed_contract_data(self):
        resolved = _simulate_resolutions(SEED_CONTRACTS)
        tickers = {r["ticker"] for r in resolved}
        seed_ids = {sc.id for sc in SEED_CONTRACTS}
        assert tickers == seed_ids


class TestRealDataEvaluation:
    """Run all strategies against real seed contracts with simulated resolutions."""

    @pytest.fixture
    def resolved(self):
        return _simulate_resolutions(SEED_CONTRACTS, seed=42)

    def test_hash_bias_produces_valid_result(self, resolved):
        result = _evaluate_strategy_on_resolved(HashBiasStrategy(), resolved)
        assert 0.0 <= result["brier_score"] <= 1.0
        assert result["total_markets"] == len(SEED_CONTRACTS)
        assert result["opinions_generated"] + result["opinions_skipped"] == len(SEED_CONTRACTS)

    def test_mean_reversion_produces_valid_result(self, resolved):
        result = _evaluate_strategy_on_resolved(MeanReversionStrategy(), resolved)
        assert 0.0 <= result["brier_score"] <= 1.0

    def test_calibration_aware_produces_valid_result(self, resolved):
        result = _evaluate_strategy_on_resolved(CalibrationAwareStrategy(), resolved)
        assert 0.0 <= result["brier_score"] <= 1.0

    def test_all_strategies_have_category_breakdown(self, resolved):
        for name in ["hash_bias", "mean_reversion", "calibration_aware"]:
            strategy = get_strategy(name)
            result = _evaluate_strategy_on_resolved(strategy, resolved)
            assert "by_category" in result
            # Should have at least some categories from seed contracts
            assert len(result["by_category"]) > 0

    def test_market_baseline_consistent(self, resolved):
        """All strategies should report the same market baseline Brier."""
        baselines = []
        for name in ["hash_bias", "mean_reversion", "calibration_aware"]:
            strategy = get_strategy(name)
            result = _evaluate_strategy_on_resolved(strategy, resolved)
            baselines.append(result["market_brier"])
        assert len(set(baselines)) == 1

    def test_delta_sign_matches_beats_market(self, resolved):
        """delta < 0 should correspond to beats_market=True."""
        for name in ["hash_bias", "mean_reversion", "calibration_aware"]:
            strategy = get_strategy(name)
            result = _evaluate_strategy_on_resolved(strategy, resolved)
            if result["delta"] < 0:
                assert result["beats_market"] is True
            elif result["delta"] > 0:
                assert result["beats_market"] is False


class TestStrategyComparison:
    """Compare strategies head-to-head on real seed data."""

    @pytest.fixture
    def results(self):
        resolved = _simulate_resolutions(SEED_CONTRACTS, seed=42)
        return {
            name: _evaluate_strategy_on_resolved(get_strategy(name), resolved)
            for name in ["hash_bias", "mean_reversion", "calibration_aware"]
        }

    def test_comparison_report_complete(self, results):
        """Each strategy should have a complete evaluation report."""
        for name, result in results.items():
            assert "brier_score" in result
            assert "market_brier" in result
            assert "delta" in result
            assert "beats_market" in result
            assert "coverage" in result
            assert "by_category" in result

    def test_strategies_produce_different_scores(self, results):
        """Strategies should generally produce different Brier scores."""
        scores = [r["brier_score"] for r in results.values()]
        # At least 2 of 3 should differ (hash_bias is deterministic but different from others)
        assert len(set(scores)) >= 2

    def test_best_strategy_identified(self, results):
        """We should be able to identify the best-performing strategy."""
        best = min(results.items(), key=lambda x: x[1]["brier_score"])
        assert best[0] in results
        assert best[1]["brier_score"] <= max(r["brier_score"] for r in results.values())


class TestMultiSeedRobustness:
    """Run evaluation across multiple resolution seeds to check robustness."""

    def test_strategy_ranking_across_seeds(self):
        """Run 5 different resolution seeds and check strategy consistency."""
        wins = {name: 0 for name in ["hash_bias", "mean_reversion", "calibration_aware"]}

        for seed in [42, 99, 123, 456, 789]:
            resolved = _simulate_resolutions(SEED_CONTRACTS, seed=seed)
            best_name = None
            best_brier = 1.0
            for name in wins:
                strategy = get_strategy(name)
                result = _evaluate_strategy_on_resolved(strategy, resolved)
                if result["brier_score"] < best_brier:
                    best_brier = result["brier_score"]
                    best_name = name
            if best_name:
                wins[best_name] += 1

        # At least one strategy should win at least once
        assert max(wins.values()) >= 1
        # All strategies should have been evaluated
        total_wins = sum(wins.values())
        assert total_wins == 5

    def test_no_strategy_always_loses(self):
        """No strategy should have a Brier score of 1.0 (worst possible) on any seed."""
        for seed in [42, 99, 123]:
            resolved = _simulate_resolutions(SEED_CONTRACTS, seed=seed)
            for name in ["hash_bias", "mean_reversion", "calibration_aware"]:
                strategy = get_strategy(name)
                result = _evaluate_strategy_on_resolved(strategy, resolved)
                assert result["brier_score"] < 1.0, f"{name} scored 1.0 on seed {seed}"


class TestEvaluationReportGeneration:
    """Verify we can generate a full comparison report."""

    def test_full_report(self):
        """Generate a full comparison report across all strategies and seeds."""
        resolved = _simulate_resolutions(SEED_CONTRACTS, seed=42)
        reports = []

        for name in ["hash_bias", "mean_reversion", "calibration_aware"]:
            strategy = get_strategy(name)
            report = _evaluate_strategy_on_resolved(strategy, resolved)
            reports.append(report)

        # Sort by Brier score (best first)
        reports.sort(key=lambda r: r["brier_score"])

        # Best strategy should have lowest Brier
        assert reports[0]["brier_score"] <= reports[-1]["brier_score"]

        # All should reference same market baseline
        baselines = {r["market_brier"] for r in reports}
        assert len(baselines) == 1

        # Report should be printable (no errors)
        for r in reports:
            line = f"{r['strategy']:25s}  Brier={r['brier_score']:.4f}  Market={r['market_brier']:.4f}  Delta={r['delta']:+.4f}  Coverage={r['coverage']:.0%}"
            assert len(line) > 0
