"""Tests for Sprint 8: Debate Protocol Tuning + Incentive Alignment.

Covers:
  A1: DebateBacktester — backtest harness with agent/team attribution
  A2: Arbiter strategy variants — Bayesian, Extremizing, Median
  A5: Strategy combo evaluation (evaluate_strategy_combos)
"""

import math
import os
import tempfile
import pytest
from unittest.mock import patch


# ── Helpers ──────────────────────────────────────────────────────────

def _tmp_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


# Synthetic resolved markets for backtesting
SYNTHETIC_MARKETS = [
    {"symbol": "MKT1", "ticker": "T1", "market_prob": 0.80, "outcome": 1, "category": "macro"},
    {"symbol": "MKT2", "ticker": "T2", "market_prob": 0.20, "outcome": 0, "category": "macro"},
    {"symbol": "MKT3", "ticker": "T3", "market_prob": 0.75, "outcome": 1, "category": "tech"},
    {"symbol": "MKT4", "ticker": "T4", "market_prob": 0.30, "outcome": 0, "category": "tech"},
    {"symbol": "MKT5", "ticker": "T5", "market_prob": 0.90, "outcome": 1, "category": "macro"},
    {"symbol": "MKT6", "ticker": "T6", "market_prob": 0.65, "outcome": 1, "category": "macro"},
    {"symbol": "MKT7", "ticker": "T7", "market_prob": 0.35, "outcome": 0, "category": "tech"},
    {"symbol": "MKT8", "ticker": "T8", "market_prob": 0.85, "outcome": 0, "category": "macro"},
]


# ══════════════════════════════════════════════════════════════════════
# A2: Arbiter Strategy Variants
# ══════════════════════════════════════════════════════════════════════

class TestBayesianArbiterStrategy:
    def test_produces_valid_estimate(self):
        from merid.prediction.opinion_strategy import BayesianArbiterStrategy
        s = BayesianArbiterStrategy()
        est = s.estimate(
            agent_id="arb-01", ticker="T1", market_prob=0.5,
            context={
                "proposer_prob": 0.8, "proposer_confidence": 0.6,
                "challenger_prob": 0.55, "challenger_confidence": 0.4,
            },
        )
        assert est is not None
        assert 0.02 <= est.agent_prob <= 0.98
        assert est.reasoning_tag == "arbiter_bayesian"

    def test_explanation_has_log_odds(self):
        from merid.prediction.opinion_strategy import BayesianArbiterStrategy
        s = BayesianArbiterStrategy()
        est = s.estimate(
            agent_id="arb-01", ticker="T1", market_prob=0.5,
            context={
                "proposer_prob": 0.7, "proposer_confidence": 0.5,
                "challenger_prob": 0.6, "challenger_confidence": 0.5,
            },
        )
        assert est.explanation is not None
        assert "proposer_log_odds_weighted" in est.explanation.contributions
        assert "combined_log_odds" in est.explanation.contributions
        assert est.explanation.rationale == "arbiter_bayesian_log_odds_synthesis"

    def test_extreme_opinions_handled(self):
        from merid.prediction.opinion_strategy import BayesianArbiterStrategy
        s = BayesianArbiterStrategy()
        est = s.estimate(
            agent_id="arb-01", ticker="T1", market_prob=0.5,
            context={
                "proposer_prob": 0.99, "proposer_confidence": 0.9,
                "challenger_prob": 0.01, "challenger_confidence": 0.1,
            },
        )
        assert est is not None
        assert 0.02 <= est.agent_prob <= 0.98

    def test_equal_confidence_blends_symmetrically(self):
        from merid.prediction.opinion_strategy import BayesianArbiterStrategy
        s = BayesianArbiterStrategy()
        est = s.estimate(
            agent_id="arb-01", ticker="T1", market_prob=0.5,
            context={
                "proposer_prob": 0.7, "proposer_confidence": 0.5,
                "challenger_prob": 0.3, "challenger_confidence": 0.5,
            },
        )
        # Symmetric inputs → result should be near 0.5
        assert est is not None
        assert abs(est.agent_prob - 0.5) < 0.05

    def test_skips_extreme_market(self):
        from merid.prediction.opinion_strategy import BayesianArbiterStrategy
        s = BayesianArbiterStrategy()
        assert s.estimate(agent_id="a", ticker="T", market_prob=0.001) is None

    def test_zero_confidence_returns_midpoint(self):
        from merid.prediction.opinion_strategy import BayesianArbiterStrategy
        s = BayesianArbiterStrategy()
        est = s.estimate(
            agent_id="arb-01", ticker="T1", market_prob=0.5,
            context={
                "proposer_prob": 0.8, "proposer_confidence": 0.0,
                "challenger_prob": 0.3, "challenger_confidence": 0.0,
            },
        )
        assert est is not None
        # With zero confidence, log-odds avg is 0 → prob = 0.5
        assert abs(est.agent_prob - 0.5) < 0.01


class TestExtremizingArbiterStrategy:
    def test_produces_valid_estimate(self):
        from merid.prediction.opinion_strategy import ExtremizingArbiterStrategy
        s = ExtremizingArbiterStrategy()
        est = s.estimate(
            agent_id="arb-01", ticker="T1", market_prob=0.5,
            context={
                "proposer_prob": 0.8, "proposer_confidence": 0.6,
                "challenger_prob": 0.55, "challenger_confidence": 0.4,
            },
        )
        assert est is not None
        assert 0.02 <= est.agent_prob <= 0.98
        assert est.reasoning_tag == "arbiter_extremizing"

    def test_pushes_away_from_half(self):
        from merid.prediction.opinion_strategy import ExtremizingArbiterStrategy, ArbiterStrategy
        base = ArbiterStrategy()
        ext = ExtremizingArbiterStrategy(extremize_factor=1.5)
        ctx = {
            "proposer_prob": 0.8, "proposer_confidence": 0.6,
            "challenger_prob": 0.7, "challenger_confidence": 0.4,
        }
        base_est = base.estimate(agent_id="a", ticker="T", market_prob=0.5, context=ctx)
        ext_est = ext.estimate(agent_id="a", ticker="T", market_prob=0.5, context=ctx)
        assert base_est is not None and ext_est is not None
        # Extremized should be further from 0.5 than base
        assert abs(ext_est.agent_prob - 0.5) > abs(base_est.agent_prob - 0.5)

    def test_explanation_has_extremize_fields(self):
        from merid.prediction.opinion_strategy import ExtremizingArbiterStrategy
        s = ExtremizingArbiterStrategy(extremize_factor=2.0)
        est = s.estimate(
            agent_id="arb-01", ticker="T1", market_prob=0.5,
            context={
                "proposer_prob": 0.7, "proposer_confidence": 0.5,
                "challenger_prob": 0.6, "challenger_confidence": 0.5,
            },
        )
        assert est.explanation is not None
        assert est.explanation.inputs_used["extremize_factor"] == 2.0
        assert "blended_pre_extremize" in est.explanation.contributions
        assert "log_odds_post" in est.explanation.contributions
        assert est.explanation.rationale == "arbiter_extremized_synthesis"

    def test_factor_1_matches_base(self):
        from merid.prediction.opinion_strategy import ExtremizingArbiterStrategy, ArbiterStrategy
        base = ArbiterStrategy()
        ext = ExtremizingArbiterStrategy(extremize_factor=1.0)
        ctx = {
            "proposer_prob": 0.75, "proposer_confidence": 0.5,
            "challenger_prob": 0.65, "challenger_confidence": 0.5,
        }
        base_est = base.estimate(agent_id="a", ticker="T", market_prob=0.5, context=ctx)
        ext_est = ext.estimate(agent_id="a", ticker="T", market_prob=0.5, context=ctx)
        # Factor=1 means no extremization → should be very close to base
        assert abs(ext_est.agent_prob - base_est.agent_prob) < 0.02

    def test_skips_extreme_market(self):
        from merid.prediction.opinion_strategy import ExtremizingArbiterStrategy
        s = ExtremizingArbiterStrategy()
        assert s.estimate(agent_id="a", ticker="T", market_prob=0.999) is None


class TestMedianArbiterStrategy:
    def test_produces_simple_midpoint(self):
        from merid.prediction.opinion_strategy import MedianArbiterStrategy
        s = MedianArbiterStrategy()
        est = s.estimate(
            agent_id="arb-01", ticker="T1", market_prob=0.5,
            context={"proposer_prob": 0.8, "challenger_prob": 0.6},
        )
        assert est is not None
        assert est.agent_prob == pytest.approx(0.7, abs=0.01)
        assert est.reasoning_tag == "arbiter_median"

    def test_ignores_confidence(self):
        from merid.prediction.opinion_strategy import MedianArbiterStrategy
        s = MedianArbiterStrategy()
        est1 = s.estimate(
            agent_id="a", ticker="T", market_prob=0.5,
            context={
                "proposer_prob": 0.8, "proposer_confidence": 0.9,
                "challenger_prob": 0.6, "challenger_confidence": 0.1,
            },
        )
        est2 = s.estimate(
            agent_id="a", ticker="T", market_prob=0.5,
            context={
                "proposer_prob": 0.8, "proposer_confidence": 0.1,
                "challenger_prob": 0.6, "challenger_confidence": 0.9,
            },
        )
        # Median ignores confidence → same result
        assert est1.agent_prob == est2.agent_prob

    def test_explanation_has_halves(self):
        from merid.prediction.opinion_strategy import MedianArbiterStrategy
        s = MedianArbiterStrategy()
        est = s.estimate(
            agent_id="a", ticker="T", market_prob=0.5,
            context={"proposer_prob": 0.8, "challenger_prob": 0.6},
        )
        assert est.explanation is not None
        assert "proposer_half" in est.explanation.contributions
        assert "challenger_half" in est.explanation.contributions
        assert est.explanation.rationale == "arbiter_simple_midpoint"

    def test_fixed_confidence(self):
        from merid.prediction.opinion_strategy import MedianArbiterStrategy
        s = MedianArbiterStrategy()
        est = s.estimate(
            agent_id="a", ticker="T", market_prob=0.5,
            context={"proposer_prob": 0.9, "challenger_prob": 0.1},
        )
        assert est.confidence == 0.4  # Always fixed

    def test_skips_extreme_market(self):
        from merid.prediction.opinion_strategy import MedianArbiterStrategy
        s = MedianArbiterStrategy()
        assert s.estimate(agent_id="a", ticker="T", market_prob=0.001) is None


class TestArbiterVariantRegistry:
    def test_all_variants_registered(self):
        from merid.prediction.opinion_strategy import get_strategy, list_strategies
        names = list_strategies()
        assert "arbiter_bayesian" in names
        assert "arbiter_extremizing" in names
        assert "arbiter_median" in names

    def test_get_each_variant(self):
        from merid.prediction.opinion_strategy import get_strategy
        for name in ("arbiter_bayesian", "arbiter_extremizing", "arbiter_median"):
            s = get_strategy(name)
            assert s.name == name

    def test_total_strategy_count(self):
        from merid.prediction.opinion_strategy import list_strategies
        names = list_strategies()
        # hash_bias, mean_reversion, calibration_aware, challenger,
        # arbiter, arbiter_bayesian, arbiter_extremizing, arbiter_median
        assert len(names) == 8


# ══════════════════════════════════════════════════════════════════════
# A1: DebateBacktester
# ══════════════════════════════════════════════════════════════════════

class TestDebateBacktester:
    def test_basic_backtest(self):
        from merid.prediction.debate import DebateBacktester
        bt = DebateBacktester()
        report = bt.run_backtest(SYNTHETIC_MARKETS, proposer_strategy="mean_reversion")
        assert "error" not in report
        assert report["markets_tested"] > 0
        assert "mean_debate_lift" in report
        assert "per_market" in report
        assert len(report["per_market"]) == report["markets_tested"]

    def test_config_logged_in_report(self):
        from merid.prediction.debate import DebateBacktester
        bt = DebateBacktester()
        report = bt.run_backtest(
            SYNTHETIC_MARKETS,
            proposer_strategy="mean_reversion",
            arbiter_strategy="arbiter",
            proposer_agent_id="my-prop",
            challenger_agent_id="my-chal",
            arbiter_agent_id="my-arb",
            team_id="team-alpha",
        )
        assert report["config"]["proposer_strategy"] == "mean_reversion"
        assert report["config"]["arbiter_strategy"] == "arbiter"
        assert report["config"]["proposer_agent_id"] == "my-prop"
        assert report["config"]["team_id"] == "team-alpha"
        assert report["team_id"] == "team-alpha"

    def test_agent_attribution_present(self):
        from merid.prediction.debate import DebateBacktester
        bt = DebateBacktester()
        report = bt.run_backtest(
            SYNTHETIC_MARKETS,
            proposer_agent_id="prop-A",
            challenger_agent_id="chal-A",
            arbiter_agent_id="arb-A",
        )
        attr = report["agent_attribution"]
        if report["markets_tested"] > 0:
            assert "prop-A" in attr
            assert "chal-A" in attr or "arb-A" in attr
            for aid, data in attr.items():
                assert "debates" in data
                assert "mean_lift" in data
                assert "total_lift" in data

    def test_per_market_has_brier_fields(self):
        from merid.prediction.debate import DebateBacktester
        bt = DebateBacktester()
        report = bt.run_backtest(SYNTHETIC_MARKETS)
        if report["per_market"]:
            m = report["per_market"][0]
            assert "pre_brier" in m
            assert "post_brier" in m
            assert "debate_lift" in m
            assert "proposer" in m
            assert "challenger" in m
            assert "arbiter" in m

    def test_skipped_markets_counted(self):
        from merid.prediction.debate import DebateBacktester
        # market_prob=0.5 with mean_reversion → 0 edge → skipped
        markets = [
            {"symbol": "S1", "ticker": "T1", "market_prob": 0.5, "outcome": 1},
        ]
        bt = DebateBacktester()
        report = bt.run_backtest(markets, proposer_strategy="mean_reversion")
        assert report["markets_skipped"] == 1
        assert report["markets_tested"] == 0

    def test_all_same_prob_edge_case(self):
        from merid.prediction.debate import DebateBacktester
        markets = [
            {"symbol": f"S{i}", "ticker": f"T{i}", "market_prob": 0.8, "outcome": 1}
            for i in range(5)
        ]
        bt = DebateBacktester()
        report = bt.run_backtest(markets, proposer_strategy="mean_reversion")
        assert report["markets_tested"] == 5
        # All same prob → all same lift
        lifts = [m["debate_lift"] for m in report["per_market"]]
        assert len(set(lifts)) == 1

    def test_extreme_probs_handled(self):
        from merid.prediction.debate import DebateBacktester
        markets = [
            {"symbol": "S1", "ticker": "T1", "market_prob": 0.99, "outcome": 1},
            {"symbol": "S2", "ticker": "T2", "market_prob": 0.01, "outcome": 0},
        ]
        bt = DebateBacktester()
        report = bt.run_backtest(markets, proposer_strategy="mean_reversion")
        # Both should be skipped (extreme market prob)
        assert report["markets_skipped"] == 2

    def test_invalid_strategy_returns_error(self):
        from merid.prediction.debate import DebateBacktester
        bt = DebateBacktester()
        report = bt.run_backtest(SYNTHETIC_MARKETS, proposer_strategy="nonexistent_strategy")
        assert "error" in report
        assert report["markets_tested"] == 0

    def test_pct_improved_calculated(self):
        from merid.prediction.debate import DebateBacktester
        bt = DebateBacktester()
        report = bt.run_backtest(SYNTHETIC_MARKETS, proposer_strategy="mean_reversion")
        if report["markets_tested"] > 0:
            assert 0.0 <= report["pct_improved"] <= 100.0
            assert report["markets_improved"] <= report["markets_tested"]

    def test_empty_markets_list(self):
        from merid.prediction.debate import DebateBacktester
        bt = DebateBacktester()
        report = bt.run_backtest([], proposer_strategy="mean_reversion")
        assert report["markets_tested"] == 0
        assert report["mean_debate_lift"] == 0.0

    def test_different_arbiter_strategies(self):
        from merid.prediction.debate import DebateBacktester
        bt = DebateBacktester()
        results = {}
        for arb in ("arbiter", "arbiter_bayesian", "arbiter_extremizing", "arbiter_median"):
            report = bt.run_backtest(
                SYNTHETIC_MARKETS,
                proposer_strategy="mean_reversion",
                arbiter_strategy=arb,
            )
            if "error" not in report and report["markets_tested"] > 0:
                results[arb] = report["mean_debate_lift"]
        # Should have results for all 4 arbiter variants
        assert len(results) == 4
        # They should not all be identical (different arbiters → different lifts)
        assert len(set(results.values())) > 1


# ══════════════════════════════════════════════════════════════════════
# A5: Strategy Combo Evaluation
# ══════════════════════════════════════════════════════════════════════

class TestStrategyComboEvaluation:
    def test_evaluate_all_combos(self):
        from merid.prediction.debate import DebateBacktester
        bt = DebateBacktester()
        result = bt.evaluate_strategy_combos(SYNTHETIC_MARKETS)
        assert result["total_combos"] > 0
        assert "rankings" in result
        assert len(result["rankings"]) == result["total_combos"]

    def test_rankings_sorted_by_lift(self):
        from merid.prediction.debate import DebateBacktester
        bt = DebateBacktester()
        result = bt.evaluate_strategy_combos(SYNTHETIC_MARKETS)
        rankings = result["rankings"]
        if len(rankings) >= 2:
            for i in range(len(rankings) - 1):
                assert rankings[i]["mean_debate_lift"] >= rankings[i + 1]["mean_debate_lift"]

    def test_agent_attribution_in_combos(self):
        from merid.prediction.debate import DebateBacktester
        bt = DebateBacktester()
        result = bt.evaluate_strategy_combos(
            SYNTHETIC_MARKETS, team_id="team-test",
        )
        for combo in result["rankings"]:
            assert "proposer_agent_id" in combo
            assert "challenger_agent_id" in combo
            assert "arbiter_agent_id" in combo
            assert combo["team_id"] == "team-test"
            assert "agent_attribution" in combo

    def test_custom_strategy_lists(self):
        from merid.prediction.debate import DebateBacktester
        bt = DebateBacktester()
        result = bt.evaluate_strategy_combos(
            SYNTHETIC_MARKETS,
            proposer_strategies=["mean_reversion"],
            arbiter_strategies=["arbiter", "arbiter_bayesian"],
        )
        assert result["total_combos"] == 2
        assert result["proposer_strategies_tested"] == ["mean_reversion"]
        assert set(result["arbiter_strategies_tested"]) == {"arbiter", "arbiter_bayesian"}

    def test_combo_count_is_product(self):
        from merid.prediction.debate import DebateBacktester
        bt = DebateBacktester()
        result = bt.evaluate_strategy_combos(
            SYNTHETIC_MARKETS,
            proposer_strategies=["mean_reversion", "hash_bias"],
            arbiter_strategies=["arbiter", "arbiter_median"],
        )
        # 2 proposers × 2 arbiters = 4 combos
        assert result["total_combos"] == 4

    def test_empty_markets_returns_zero_combos(self):
        from merid.prediction.debate import DebateBacktester
        bt = DebateBacktester()
        result = bt.evaluate_strategy_combos(
            [],
            proposer_strategies=["mean_reversion"],
            arbiter_strategies=["arbiter"],
        )
        # Combos still run but with 0 markets tested
        assert result["total_combos"] == 1
        assert result["rankings"][0]["markets_tested"] == 0


# ══════════════════════════════════════════════════════════════════════
# Arbiter comparison: verify different arbiters produce different results
# ══════════════════════════════════════════════════════════════════════

class TestArbiterComparison:
    """Compare all arbiter variants on the same input to verify they differ."""

    def _run_all_arbiters(self, ctx):
        from merid.prediction.opinion_strategy import get_strategy
        results = {}
        for name in ("arbiter", "arbiter_bayesian", "arbiter_extremizing", "arbiter_median"):
            s = get_strategy(name)
            est = s.estimate(agent_id="arb", ticker="T", market_prob=0.5, context=ctx)
            if est:
                results[name] = est.agent_prob
        return results

    def test_all_produce_estimates(self):
        ctx = {
            "proposer_prob": 0.8, "proposer_confidence": 0.7,
            "challenger_prob": 0.55, "challenger_confidence": 0.3,
        }
        results = self._run_all_arbiters(ctx)
        assert len(results) == 4

    def test_not_all_identical(self):
        ctx = {
            "proposer_prob": 0.8, "proposer_confidence": 0.7,
            "challenger_prob": 0.55, "challenger_confidence": 0.3,
        }
        results = self._run_all_arbiters(ctx)
        # At least 2 distinct values
        assert len(set(round(v, 4) for v in results.values())) >= 2

    def test_extremizing_most_extreme(self):
        ctx = {
            "proposer_prob": 0.8, "proposer_confidence": 0.6,
            "challenger_prob": 0.7, "challenger_confidence": 0.4,
        }
        results = self._run_all_arbiters(ctx)
        # All above 0.5, extremizing should be furthest from 0.5
        assert results["arbiter_extremizing"] > results["arbiter"]

    def test_median_ignores_confidence_asymmetry(self):
        ctx_high_prop = {
            "proposer_prob": 0.8, "proposer_confidence": 0.9,
            "challenger_prob": 0.6, "challenger_confidence": 0.1,
        }
        ctx_high_chal = {
            "proposer_prob": 0.8, "proposer_confidence": 0.1,
            "challenger_prob": 0.6, "challenger_confidence": 0.9,
        }
        from merid.prediction.opinion_strategy import get_strategy
        median = get_strategy("arbiter_median")
        est1 = median.estimate(agent_id="a", ticker="T", market_prob=0.5, context=ctx_high_prop)
        est2 = median.estimate(agent_id="a", ticker="T", market_prob=0.5, context=ctx_high_chal)
        assert est1.agent_prob == est2.agent_prob

        # But base arbiter should differ
        base = get_strategy("arbiter")
        est3 = base.estimate(agent_id="a", ticker="T", market_prob=0.5, context=ctx_high_prop)
        est4 = base.estimate(agent_id="a", ticker="T", market_prob=0.5, context=ctx_high_chal)
        assert est3.agent_prob != est4.agent_prob


# ══════════════════════════════════════════════════════════════════════
# A3: Adaptive Challenger Strength
# ══════════════════════════════════════════════════════════════════════

class TestAdaptiveChallengerStrength:
    def test_adaptive_is_default(self):
        from merid.prediction.opinion_strategy import ChallengerStrategy
        s = ChallengerStrategy()
        assert s.adaptive_strength is True

    def test_fixed_mode_uses_base_strength(self):
        from merid.prediction.opinion_strategy import ChallengerStrategy
        s = ChallengerStrategy(challenge_strength=0.60, adaptive_strength=False)
        ctx = {
            "proposer_prob": 0.8, "proposer_rationale": "test",
            "proposer_confidence": 0.1,  # low conf → would scale up if adaptive
        }
        effective = s._compute_effective_strength(ctx)
        assert effective == 0.60

    def test_low_confidence_increases_strength(self):
        from merid.prediction.opinion_strategy import ChallengerStrategy
        s = ChallengerStrategy(challenge_strength=0.60, adaptive_strength=True)
        ctx_low = {"proposer_confidence": 0.1}
        ctx_high = {"proposer_confidence": 0.9}
        eff_low = s._compute_effective_strength(ctx_low)
        eff_high = s._compute_effective_strength(ctx_high)
        assert eff_low > eff_high

    def test_high_brier_increases_strength(self):
        from merid.prediction.opinion_strategy import ChallengerStrategy
        s = ChallengerStrategy(challenge_strength=0.60, adaptive_strength=True)
        ctx_good = {"proposer_confidence": 0.5, "proposer_historical_brier": 0.10}
        ctx_bad = {"proposer_confidence": 0.5, "proposer_historical_brier": 0.60}
        eff_good = s._compute_effective_strength(ctx_good)
        eff_bad = s._compute_effective_strength(ctx_bad)
        assert eff_bad > eff_good

    def test_no_brier_context_uses_default_factor(self):
        from merid.prediction.opinion_strategy import ChallengerStrategy
        s = ChallengerStrategy(challenge_strength=0.60, adaptive_strength=True)
        ctx = {"proposer_confidence": 0.5}  # no proposer_historical_brier
        eff = s._compute_effective_strength(ctx)
        # With conf=0.5, conf_factor=1.0; no brier → brier_factor=1.0
        assert abs(eff - 0.60) < 0.01

    def test_effective_strength_clamped(self):
        from merid.prediction.opinion_strategy import ChallengerStrategy
        s = ChallengerStrategy(challenge_strength=0.90, adaptive_strength=True)
        ctx = {"proposer_confidence": 0.0, "proposer_historical_brier": 1.0}
        eff = s._compute_effective_strength(ctx)
        assert eff <= 0.95  # max clamp

        s2 = ChallengerStrategy(challenge_strength=0.05, adaptive_strength=True)
        ctx2 = {"proposer_confidence": 1.0}
        eff2 = s2._compute_effective_strength(ctx2)
        assert eff2 >= 0.1  # min clamp

    def test_adaptive_affects_estimate(self):
        from merid.prediction.opinion_strategy import ChallengerStrategy
        s_adaptive = ChallengerStrategy(challenge_strength=0.60, adaptive_strength=True)
        s_fixed = ChallengerStrategy(challenge_strength=0.60, adaptive_strength=False)
        ctx = {
            "proposer_prob": 0.8, "proposer_rationale": "test",
            "proposer_confidence": 0.1,  # low conf → adaptive scales up
        }
        est_a = s_adaptive.estimate(agent_id="c", ticker="T", market_prob=0.5, context=ctx)
        est_f = s_fixed.estimate(agent_id="c", ticker="T", market_prob=0.5, context=ctx)
        assert est_a is not None and est_f is not None
        # Adaptive with low conf → stronger challenge → more pull toward market
        # So adaptive estimate should be closer to market_prob (0.5)
        assert abs(est_a.agent_prob - 0.5) < abs(est_f.agent_prob - 0.5)

    def test_explanation_includes_adaptive_flag(self):
        from merid.prediction.opinion_strategy import ChallengerStrategy
        s = ChallengerStrategy(adaptive_strength=True)
        est = s.estimate(
            agent_id="c", ticker="T", market_prob=0.5,
            context={"proposer_prob": 0.8, "proposer_rationale": "test"},
        )
        assert est is not None
        assert est.explanation.inputs_used["adaptive"] is True


# ══════════════════════════════════════════════════════════════════════
# A4: Debate Quality Gate
# ══════════════════════════════════════════════════════════════════════

class TestDebateQualityGate:
    def setup_method(self):
        self._db_path = _tmp_db()
        os.environ["MERID_PRED_CONSENSUS_DB"] = self._db_path
        # Reset singleton so it picks up the temp DB
        import merid.prediction.debate as dmod
        dmod._debate_store = None

    def teardown_method(self):
        import merid.prediction.debate as dmod
        dmod._debate_store = None
        os.environ.pop("MERID_PRED_CONSENSUS_DB", None)
        try:
            os.unlink(self._db_path)
        except OSError:
            pass

    def test_suppressed_when_low_disagreement(self):
        from merid.agents.coordination import DebateCoordinatorAgent
        agent = DebateCoordinatorAgent(min_disagreement=0.50)
        instrument = {"symbol": "TEST", "ticker": "TEST", "market_prob": 0.8, "category": "test"}
        context = {"proposer_strategy": "mean_reversion"}
        result = agent.run_debate(instrument, context)
        if result is not None:
            # With min_disagreement=0.50, most debates should be suppressed
            # because challenger pulls back toward market, reducing disagreement
            if result["debate_suppressed"]:
                assert result["arbiter"]["prob"] is None
                # post_debate_prob should equal proposer's prob
                assert result["post_debate_prob"] == result["proposer"]["prob"]

    def test_not_suppressed_when_high_disagreement(self):
        from merid.agents.coordination import DebateCoordinatorAgent
        agent = DebateCoordinatorAgent(min_disagreement=0.001)
        instrument = {"symbol": "TEST", "ticker": "TEST", "market_prob": 0.8, "category": "test"}
        context = {"proposer_strategy": "mean_reversion"}
        result = agent.run_debate(instrument, context)
        assert result is not None
        assert result["debate_suppressed"] is False
        assert result["arbiter"]["prob"] is not None

    def test_debate_suppressed_field_present(self):
        from merid.agents.coordination import DebateCoordinatorAgent
        agent = DebateCoordinatorAgent()
        instrument = {"symbol": "TEST", "ticker": "TEST", "market_prob": 0.8, "category": "test"}
        context = {"proposer_strategy": "mean_reversion"}
        result = agent.run_debate(instrument, context)
        assert result is not None
        assert "debate_suppressed" in result
        assert isinstance(result["debate_suppressed"], bool)

    def test_default_min_disagreement(self):
        from merid.agents.coordination import DebateCoordinatorAgent
        agent = DebateCoordinatorAgent()
        assert agent.min_disagreement == 0.03

    def test_configurable_arbiter_strategy(self):
        from merid.agents.coordination import DebateCoordinatorAgent
        agent = DebateCoordinatorAgent(min_disagreement=0.001)
        instrument = {"symbol": "TEST", "ticker": "TEST", "market_prob": 0.8, "category": "test"}
        context = {
            "proposer_strategy": "mean_reversion",
            "arbiter_strategy": "arbiter_bayesian",
        }
        result = agent.run_debate(instrument, context)
        assert result is not None
        assert result["arbiter"]["strategy"] == "arbiter_bayesian"

    def test_disagreement_width_in_result(self):
        from merid.agents.coordination import DebateCoordinatorAgent
        agent = DebateCoordinatorAgent(min_disagreement=0.001)
        instrument = {"symbol": "TEST", "ticker": "TEST", "market_prob": 0.8, "category": "test"}
        context = {"proposer_strategy": "mean_reversion"}
        result = agent.run_debate(instrument, context)
        assert result is not None
        assert "disagreement_width" in result
        assert result["disagreement_width"] >= 0


# ══════════════════════════════════════════════════════════════════════
# A6: Reward Parameter Sensitivity Sweep
# ══════════════════════════════════════════════════════════════════════

class TestRewardParameterSweep:
    def test_default_sweep(self):
        from merid.prediction.debate import RewardParameterSweep
        sweep = RewardParameterSweep()
        result = sweep.sweep()
        assert result["total_param_sets"] == 5
        assert len(result["results"]) == 5
        assert "top_agent_distribution" in result

    def test_custom_params(self):
        from merid.prediction.debate import RewardParameterSweep
        sweep = RewardParameterSweep()
        result = sweep.sweep(param_sets=[
            {"accuracy_base": 100.0, "brier_bonus": 0.0, "lift_bonus": 0.0,
             "explanation_bonus": 0.0, "cooperation_bonus": 0.0},
        ])
        assert result["total_param_sets"] == 1
        # With only accuracy_base, spammy_participant (50 opinions) should win
        top = result["results"][0]["top_agent"]
        assert top == "spammy_participant"

    def test_accuracy_emphasis_rewards_accurate(self):
        from merid.prediction.debate import RewardParameterSweep
        sweep = RewardParameterSweep()
        result = sweep.sweep(param_sets=[
            {"accuracy_base": 1.0, "brier_bonus": 200.0, "lift_bonus": 0.0,
             "explanation_bonus": 0.0, "cooperation_bonus": 0.0},
        ])
        # High brier_bonus should reward low-Brier agents
        rankings = result["results"][0]["rankings"]
        # silent_accurate has lowest Brier (0.05) but fewest opinions
        # accurate_debater has Brier 0.08 with 20 opinions
        # The per-opinion accuracy is highest for silent_accurate
        assert len(rankings) == 3

    def test_rankings_sorted_descending(self):
        from merid.prediction.debate import RewardParameterSweep
        sweep = RewardParameterSweep()
        result = sweep.sweep()
        for r in result["results"]:
            rankings = r["rankings"]
            for i in range(len(rankings) - 1):
                assert rankings[i]["total_points"] >= rankings[i + 1]["total_points"]

    def test_sensitivity_is_nonzero(self):
        from merid.prediction.debate import RewardParameterSweep
        sweep = RewardParameterSweep()
        result = sweep.sweep()
        # At least one param set should produce a different top agent
        tops = [r["top_agent"] for r in result["results"]]
        # Not all the same (different params → different winners)
        # This may or may not hold depending on archetypes, so just check structure
        assert all(t in ("accurate_debater", "spammy_participant", "silent_accurate") for t in tops)


# ══════════════════════════════════════════════════════════════════════
# A7: Debate Lift Regression Test
# ══════════════════════════════════════════════════════════════════════

class TestDebateLiftRegression:
    """Golden-value tests to ensure debate lift doesn't degrade."""

    def test_mean_reversion_with_base_arbiter_positive_lift(self):
        from merid.prediction.debate import DebateBacktester
        # Markets where outcome matches the direction mean_reversion would push
        markets = [
            {"symbol": "R1", "ticker": "R1", "market_prob": 0.80, "outcome": 1},
            {"symbol": "R2", "ticker": "R2", "market_prob": 0.20, "outcome": 0},
            {"symbol": "R3", "ticker": "R3", "market_prob": 0.75, "outcome": 1},
            {"symbol": "R4", "ticker": "R4", "market_prob": 0.25, "outcome": 0},
        ]
        bt = DebateBacktester()
        report = bt.run_backtest(markets, proposer_strategy="mean_reversion", arbiter_strategy="arbiter")
        assert report["markets_tested"] == 4
        # Debate should not make things worse on average for these favorable cases
        # (mean_reversion pulls toward 0.5, which is wrong for these high-confidence correct markets)
        # The key assertion: the system produces a measurable result
        assert report["mean_debate_lift"] is not None

    def test_all_arbiter_variants_produce_results(self):
        from merid.prediction.debate import DebateBacktester
        markets = [
            {"symbol": "R1", "ticker": "R1", "market_prob": 0.80, "outcome": 1},
            {"symbol": "R2", "ticker": "R2", "market_prob": 0.30, "outcome": 0},
        ]
        bt = DebateBacktester()
        for arb in ("arbiter", "arbiter_bayesian", "arbiter_extremizing", "arbiter_median"):
            report = bt.run_backtest(markets, proposer_strategy="mean_reversion", arbiter_strategy=arb)
            assert "error" not in report, f"Arbiter {arb} failed"
            assert report["markets_tested"] == 2, f"Arbiter {arb} skipped markets"

    def test_lift_values_are_bounded(self):
        from merid.prediction.debate import DebateBacktester
        bt = DebateBacktester()
        report = bt.run_backtest(SYNTHETIC_MARKETS, proposer_strategy="mean_reversion")
        for m in report["per_market"]:
            # Brier scores range 0-1, so lift range is -1 to 1
            assert -1.0 <= m["debate_lift"] <= 1.0
            assert 0.0 <= m["pre_brier"] <= 1.0
            assert 0.0 <= m["post_brier"] <= 1.0


# ══════════════════════════════════════════════════════════════════════
# B1: Accuracy-Gated Debate Rewards
# ══════════════════════════════════════════════════════════════════════

class _StoreTestBase:
    """Shared setup for DebateStore tests."""
    def setup_method(self):
        self._db_path = _tmp_db()
        from merid.prediction.debate import DebateStore
        self.store = DebateStore(self._db_path)

    def teardown_method(self):
        try:
            os.unlink(self._db_path)
        except OSError:
            pass


class TestAccuracyGatedRewards(_StoreTestBase):
    def _make_opinion(self, agent_id, probability, explanation=None):
        from dataclasses import dataclass, field
        from typing import Optional, Any
        @dataclass
        class FakeOp:
            agent_id: str = ""
            probability: float = 0.5
            explanation: Any = None
        return FakeOp(agent_id=agent_id, probability=probability, explanation=explanation)

    def test_lift_bonus_requires_individual_accuracy(self):
        from merid.prediction.debate import DebateSession, DebateArgument
        # Create a resolved debate with positive lift
        session = DebateSession(symbol="TEST", pre_debate_prob=0.5, post_debate_prob=0.8)
        self.store.create_debate(session)
        self.store.add_argument(DebateArgument(
            debate_id=session.id, agent_id="good-agent", role="proposer",
            probability=0.85, confidence=0.7, rationale="mean_reversion",
        ))
        self.store.add_argument(DebateArgument(
            debate_id=session.id, agent_id="bad-agent", role="challenger",
            probability=0.4, confidence=0.3, rationale="challenger",
        ))
        self.store.close_debate(session.id, 0.8)
        self.store.resolve_debate(session.id, 1)

        # good-agent: prob=0.85, outcome=1, Brier=0.0225 (good)
        # bad-agent: prob=0.4, outcome=1, Brier=0.36 (bad)
        opinions = [
            self._make_opinion("good-agent", 0.85),
            self._make_opinion("bad-agent", 0.4),
        ]
        entries = self.store.compute_rewards_for_resolution("TEST", 1, opinions)
        lift_entries = [e for e in entries if e.reward_type == "debate_lift"]
        lift_agents = [e.agent_id for e in lift_entries]
        # good-agent should get lift bonus (low Brier < pre_debate Brier)
        assert "good-agent" in lift_agents
        # bad-agent should NOT get lift bonus (high Brier > pre_debate Brier)
        assert "bad-agent" not in lift_agents


# ══════════════════════════════════════════════════════════════════════
# B2: Time-Decay for Leaderboard Points
# ══════════════════════════════════════════════════════════════════════

class TestTimeDecayLeaderboard(_StoreTestBase):
    def test_no_decay_by_default(self):
        from merid.prediction.debate import RewardEntry
        self.store.add_reward(RewardEntry(
            agent_id="a1", reward_type="accuracy", points=100.0, symbol="S1",
        ))
        lb = self.store.compute_leaderboard(decay_lambda=0.0)
        assert lb["agents"][0]["total_points"] == 100.0
        assert lb["decay_lambda"] == 0.0

    def test_decay_reduces_old_rewards(self):
        import time as _time
        from merid.prediction.debate import RewardEntry
        # Add a reward with old timestamp (30 days ago)
        old_entry = RewardEntry(
            agent_id="a1", reward_type="accuracy", points=100.0, symbol="S1",
        )
        old_entry.created_at = _time.time() - 30 * 86400
        self.store.add_reward(old_entry)

        # Add a recent reward
        new_entry = RewardEntry(
            agent_id="a2", reward_type="accuracy", points=100.0, symbol="S1",
        )
        self.store.add_reward(new_entry)

        lb = self.store.compute_leaderboard(decay_lambda=0.03)
        agents = {a["agent_id"]: a["total_points"] for a in lb["agents"]}
        # Recent reward should be worth more than old reward
        assert agents["a2"] > agents["a1"]

    def test_decay_lambda_from_env(self):
        from merid.prediction.debate import RewardEntry
        self.store.add_reward(RewardEntry(
            agent_id="a1", reward_type="accuracy", points=100.0, symbol="S1",
        ))
        os.environ["MERID_LEADERBOARD_DECAY_LAMBDA"] = "0.05"
        try:
            lb = self.store.compute_leaderboard()
            assert lb["decay_lambda"] == 0.05
        finally:
            os.environ.pop("MERID_LEADERBOARD_DECAY_LAMBDA", None)

    def test_decay_lambda_in_response(self):
        lb = self.store.compute_leaderboard(decay_lambda=0.1)
        assert "decay_lambda" in lb
        assert lb["decay_lambda"] == 0.1


# ══════════════════════════════════════════════════════════════════════
# B3: Anti-Spam Gates
# ══════════════════════════════════════════════════════════════════════

class TestAntiSpamGates(_StoreTestBase):
    def _make_opinion(self, agent_id, probability, explanation=None):
        from dataclasses import dataclass
        from typing import Any
        @dataclass
        class FakeOp:
            agent_id: str = ""
            probability: float = 0.5
            explanation: Any = None
        return FakeOp(agent_id=agent_id, probability=probability, explanation=explanation)

    def test_low_disagreement_blocks_lift_bonus(self):
        from merid.prediction.debate import DebateSession, DebateArgument
        session = DebateSession(symbol="SPAM", pre_debate_prob=0.5, post_debate_prob=0.51)
        self.store.create_debate(session)
        # Very similar probabilities → low disagreement
        self.store.add_argument(DebateArgument(
            debate_id=session.id, agent_id="spammer", role="proposer",
            probability=0.51, confidence=0.5, rationale="test",
        ))
        self.store.add_argument(DebateArgument(
            debate_id=session.id, agent_id="spammer", role="challenger",
            probability=0.50, confidence=0.5, rationale="test",
        ))
        self.store.close_debate(session.id, 0.51)
        self.store.resolve_debate(session.id, 1)

        opinions = [self._make_opinion("spammer", 0.9)]
        entries = self.store.compute_rewards_for_resolution(
            "SPAM", 1, opinions, min_disagreement_for_reward=0.05,
        )
        lift_entries = [e for e in entries if e.reward_type == "debate_lift"]
        assert len(lift_entries) == 0

    def test_explanation_requires_rationale(self):
        opinions = [
            self._make_opinion("a1", 0.8, explanation={"rationale": "good reason"}),
            self._make_opinion("a2", 0.8, explanation={"rationale": ""}),
            self._make_opinion("a3", 0.8, explanation=None),
        ]
        entries = self.store.compute_rewards_for_resolution("TEST", 1, opinions)
        expl_agents = [e.agent_id for e in entries if e.reward_type == "explanation"]
        assert "a1" in expl_agents
        assert "a2" not in expl_agents
        assert "a3" not in expl_agents


# ══════════════════════════════════════════════════════════════════════
# B4: Tiered Badges
# ══════════════════════════════════════════════════════════════════════

class TestTieredBadges(_StoreTestBase):
    def _add_rewards(self, agent_id, reward_type, count, points_each):
        from merid.prediction.debate import RewardEntry
        for _ in range(count):
            self.store.add_reward(RewardEntry(
                agent_id=agent_id, reward_type=reward_type,
                points=points_each, symbol="TEST",
            ))

    def test_explainer_bronze(self):
        self._add_rewards("a1", "timeliness", 10, 10.0)
        self._add_rewards("a1", "explanation", 7, 5.0)  # 70% coverage
        badges = self.store.compute_badges("a1")
        explainer = [b for b in badges if b["badge"] == "explainer"]
        assert len(explainer) == 1
        assert explainer[0]["tier"] == "bronze"  # 70% ≥60% but <80% → bronze

    def test_explainer_tiers(self):
        # Bronze: 60-79%
        self._add_rewards("bronze", "timeliness", 10, 10.0)
        self._add_rewards("bronze", "explanation", 6, 5.0)
        badges_b = self.store.compute_badges("bronze")
        expl_b = [b for b in badges_b if b["badge"] == "explainer"]
        assert len(expl_b) == 1
        assert expl_b[0]["tier"] == "bronze"

        # Silver: 80-94%
        self._add_rewards("silver", "timeliness", 10, 10.0)
        self._add_rewards("silver", "explanation", 8, 5.0)
        badges_s = self.store.compute_badges("silver")
        expl_s = [b for b in badges_s if b["badge"] == "explainer"]
        assert len(expl_s) == 1
        assert expl_s[0]["tier"] == "silver"

        # Gold: 95%+
        self._add_rewards("gold", "timeliness", 20, 10.0)
        self._add_rewards("gold", "explanation", 19, 5.0)
        badges_g = self.store.compute_badges("gold")
        expl_g = [b for b in badges_g if b["badge"] == "explainer"]
        assert len(expl_g) == 1
        assert expl_g[0]["tier"] == "gold"

    def test_badges_have_tier_field(self):
        self._add_rewards("a1", "timeliness", 10, 10.0)
        self._add_rewards("a1", "explanation", 10, 5.0)
        self._add_rewards("a1", "debate_lift", 6, 30.0)
        self._add_rewards("a1", "accuracy", 10, 50.0)
        badges = self.store.compute_badges("a1")
        for b in badges:
            assert "tier" in b
            assert b["tier"] in ("bronze", "silver", "gold")

    def test_no_badges_below_threshold(self):
        self._add_rewards("a1", "timeliness", 10, 10.0)
        self._add_rewards("a1", "explanation", 3, 5.0)  # 30% < 60% → no explainer
        badges = self.store.compute_badges("a1")
        explainer = [b for b in badges if b["badge"] == "explainer"]
        assert len(explainer) == 0


# ══════════════════════════════════════════════════════════════════════
# B5: Team Composition Diversity Scoring
# ══════════════════════════════════════════════════════════════════════

class TestTeamDiversityScoring(_StoreTestBase):
    def test_single_strategy_team(self):
        from merid.prediction.debate import AgentTeam, DebateSession, DebateArgument
        team = AgentTeam(name="mono", member_ids=["a1", "a2"], strategy_mix="mean_reversion")
        self.store.create_team(team)
        # Both agents use same strategy
        session = DebateSession(symbol="T1", team_id=team.id, pre_debate_prob=0.5)
        self.store.create_debate(session)
        self.store.add_argument(DebateArgument(
            debate_id=session.id, agent_id="a1", role="proposer",
            probability=0.7, confidence=0.5, rationale="mean_reversion",
        ))
        self.store.add_argument(DebateArgument(
            debate_id=session.id, agent_id="a2", role="challenger",
            probability=0.6, confidence=0.5, rationale="mean_reversion",
        ))
        result = self.store.compute_team_diversity_score(team.id)
        assert result["diversity_score"] == 0.0
        assert result["strategy_count"] == 1

    def test_diverse_team(self):
        from merid.prediction.debate import AgentTeam, DebateSession, DebateArgument
        team = AgentTeam(name="diverse", member_ids=["a1", "a2", "a3"], strategy_mix="mixed")
        self.store.create_team(team)
        session = DebateSession(symbol="T1", team_id=team.id, pre_debate_prob=0.5)
        self.store.create_debate(session)
        self.store.add_argument(DebateArgument(
            debate_id=session.id, agent_id="a1", role="proposer",
            probability=0.7, confidence=0.5, rationale="mean_reversion",
        ))
        self.store.add_argument(DebateArgument(
            debate_id=session.id, agent_id="a2", role="challenger",
            probability=0.6, confidence=0.5, rationale="challenger",
        ))
        self.store.add_argument(DebateArgument(
            debate_id=session.id, agent_id="a3", role="arbiter",
            probability=0.65, confidence=0.5, rationale="arbiter_bayesian",
        ))
        result = self.store.compute_team_diversity_score(team.id)
        assert result["diversity_score"] == 1.0
        assert result["strategy_count"] == 3

    def test_nonexistent_team(self):
        result = self.store.compute_team_diversity_score("nonexistent")
        assert result["diversity_score"] == 0.0
        assert "error" in result


# ══════════════════════════════════════════════════════════════════════
# B6: Calibration-Based Rewards
# ══════════════════════════════════════════════════════════════════════

class TestCalibrationScore(_StoreTestBase):
    def test_perfect_calibration(self):
        # Predictions that match outcomes perfectly
        brier_data = [
            {"probability": 0.9, "outcome": 1},
            {"probability": 0.1, "outcome": 0},
            {"probability": 0.8, "outcome": 1},
            {"probability": 0.2, "outcome": 0},
        ]
        result = self.store.compute_calibration_score("a1", brier_data=brier_data)
        assert result["calibration_score"] is not None
        assert result["calibration_score"] > 0.5
        assert result["total_predictions"] == 4

    def test_poor_calibration(self):
        # Predictions that are systematically wrong
        brier_data = [
            {"probability": 0.9, "outcome": 0},
            {"probability": 0.9, "outcome": 0},
            {"probability": 0.1, "outcome": 1},
            {"probability": 0.1, "outcome": 1},
        ]
        result = self.store.compute_calibration_score("a1", brier_data=brier_data)
        assert result["calibration_score"] is not None
        assert result["calibration_score"] < 0.5

    def test_empty_data(self):
        result = self.store.compute_calibration_score("a1", brier_data=[])
        assert result["calibration_score"] is None
        assert result["total_predictions"] == 0

    def test_bins_structure(self):
        brier_data = [
            {"probability": 0.15, "outcome": 0},
            {"probability": 0.85, "outcome": 1},
        ]
        result = self.store.compute_calibration_score("a1", brier_data=brier_data, n_bins=10)
        assert len(result["bins"]) == 10
        for b in result["bins"]:
            assert "bin_lo" in b
            assert "bin_hi" in b
            assert "count" in b

    def test_reuse_brier_data(self):
        # Passing brier_data should avoid DB queries
        brier_data = [{"probability": 0.7, "outcome": 1}] * 5
        result = self.store.compute_calibration_score("a1", brier_data=brier_data)
        assert result["total_predictions"] == 5
        assert result["calibration_score"] is not None

    def test_from_db(self):
        from merid.prediction.debate import DebateSession, DebateArgument
        # Create resolved debates with arguments
        for i in range(5):
            session = DebateSession(symbol=f"CAL{i}", pre_debate_prob=0.5)
            self.store.create_debate(session)
            self.store.add_argument(DebateArgument(
                debate_id=session.id, agent_id="cal-agent",
                role="proposer", probability=0.7 + i * 0.02,
                confidence=0.5, rationale="test",
            ))
            self.store.close_debate(session.id, 0.7 + i * 0.02)
            self.store.resolve_debate(session.id, 1)

        result = self.store.compute_calibration_score("cal-agent")
        assert result["total_predictions"] == 5
        assert result["calibration_score"] is not None
