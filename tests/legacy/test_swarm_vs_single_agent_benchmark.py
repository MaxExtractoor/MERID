"""
A/B Benchmark: Swarm consensus vs. single-agent baselines (S1-04).

Generates synthetic market scenarios with known outcomes, then compares:
- Swarm consensus (trust-weighted voting from multiple agents)
- Best single agent (highest individual accuracy)
- Majority vote (unweighted)
- Random baseline

Validates that swarm consensus outperforms or matches single-agent baselines.
"""

import random
import unittest
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from core.consensus_math import Vote, compute_consensus


# ── Synthetic scenario generation ────────────────────────────────────


@dataclass
class MarketScenario:
    """A synthetic market scenario with a known ground-truth outcome."""
    scenario_id: str
    true_signal: int  # +1 (bullish) or -1 (bearish)
    features: Dict[str, float] = field(default_factory=dict)


@dataclass
class AgentProfile:
    """Simulated agent with a base accuracy and trust score."""
    agent_id: str
    base_accuracy: float  # Probability of voting correctly [0, 1]
    trust: float = 1.0
    source: str = "live"
    source_srw: float = 0.9


def generate_scenarios(n: int, seed: int = 42) -> List[MarketScenario]:
    """Generate n synthetic scenarios with random ground truth."""
    rng = random.Random(seed)
    scenarios = []
    for i in range(n):
        true_signal = rng.choice([+1, -1])
        scenarios.append(MarketScenario(
            scenario_id=f"scenario-{i:04d}",
            true_signal=true_signal,
            features={
                "momentum": rng.gauss(0.1 * true_signal, 0.3),
                "volume_surge": rng.random(),
                "spread_bps": rng.gauss(20, 10),
            },
        ))
    return scenarios


def simulate_agent_vote(
    agent: AgentProfile,
    scenario: MarketScenario,
    rng: random.Random,
) -> Vote:
    """Simulate an agent voting on a scenario based on its accuracy."""
    # Agent votes correctly with probability = base_accuracy
    correct = rng.random() < agent.base_accuracy
    vote_val = scenario.true_signal if correct else -scenario.true_signal
    # Confidence correlates with accuracy but has noise
    confidence = min(1.0, max(0.1, agent.base_accuracy + rng.gauss(0, 0.1)))

    return Vote(
        agent_id=agent.agent_id,
        vote=vote_val,
        trust=agent.trust,
        confidence=confidence,
        source=agent.source,
        source_srw=agent.source_srw,
    )


# ── Benchmark runner ─────────────────────────────────────────────────


def run_benchmark(
    agents: List[AgentProfile],
    scenarios: List[MarketScenario],
    seed: int = 42,
    consensus_threshold: float = 0.0,
) -> Dict[str, float]:
    """
    Run the A/B benchmark.

    Returns dict with accuracy for:
    - swarm_consensus: trust-weighted consensus
    - majority_vote: unweighted majority
    - best_single_agent: best individual agent
    - worst_single_agent: worst individual agent
    - random_baseline: random coin flip
    """
    rng = random.Random(seed)
    n = len(scenarios)

    # Track per-agent correct counts
    agent_correct: Dict[str, int] = {a.agent_id: 0 for a in agents}
    swarm_correct = 0
    majority_correct = 0
    random_correct = 0

    for scenario in scenarios:
        votes = [simulate_agent_vote(a, scenario, rng) for a in agents]

        # --- Swarm consensus (trust-weighted) ---
        result = compute_consensus(votes, threshold=consensus_threshold)
        swarm_signal = +1 if result.consensus_score >= 0 else -1
        if swarm_signal == scenario.true_signal:
            swarm_correct += 1

        # --- Majority vote (unweighted) ---
        majority_sum = sum(v.vote for v in votes)
        majority_signal = +1 if majority_sum >= 0 else -1
        if majority_signal == scenario.true_signal:
            majority_correct += 1

        # --- Per-agent tracking ---
        for v in votes:
            if v.vote == scenario.true_signal:
                agent_correct[v.agent_id] += 1

        # --- Random baseline ---
        if rng.choice([+1, -1]) == scenario.true_signal:
            random_correct += 1

    agent_accuracies = {aid: c / n for aid, c in agent_correct.items()}
    best_single = max(agent_accuracies.values())
    worst_single = min(agent_accuracies.values())

    return {
        "swarm_consensus": swarm_correct / n,
        "majority_vote": majority_correct / n,
        "best_single_agent": best_single,
        "worst_single_agent": worst_single,
        "random_baseline": random_correct / n,
        "agent_accuracies": agent_accuracies,
    }


# ── Default agent pool ───────────────────────────────────────────────

DEFAULT_AGENTS = [
    AgentProfile("momentum-agent", base_accuracy=0.62, trust=1.2, source="price_feed", source_srw=0.95),
    AgentProfile("sentiment-agent", base_accuracy=0.58, trust=1.0, source="news", source_srw=0.85),
    AgentProfile("volume-agent", base_accuracy=0.55, trust=0.9, source="exchange", source_srw=0.90),
    AgentProfile("arb-agent", base_accuracy=0.60, trust=1.1, source="arb_scanner", source_srw=0.92),
    AgentProfile("risk-agent", base_accuracy=0.65, trust=1.5, source="risk_model", source_srw=0.98),
]


# ── Tests ────────────────────────────────────────────────────────────


class TestSwarmVsSingleAgent(unittest.TestCase):
    """Swarm consensus should outperform or match the best single agent."""

    def setUp(self):
        self.scenarios = generate_scenarios(500, seed=42)
        self.results = run_benchmark(DEFAULT_AGENTS, self.scenarios, seed=42)

    def test_swarm_beats_random(self):
        self.assertGreater(
            self.results["swarm_consensus"],
            self.results["random_baseline"] + 0.05,
            "Swarm should significantly beat random baseline",
        )

    def test_swarm_beats_worst_agent(self):
        self.assertGreater(
            self.results["swarm_consensus"],
            self.results["worst_single_agent"],
            "Swarm should beat the worst single agent",
        )

    def test_swarm_matches_or_beats_best_agent(self):
        # Swarm should be within 3% of best agent or better
        self.assertGreaterEqual(
            self.results["swarm_consensus"],
            self.results["best_single_agent"] - 0.03,
            "Swarm should match or beat best single agent (within 3%)",
        )

    def test_swarm_beats_majority_or_close(self):
        # Trust-weighted should be at least as good as unweighted majority
        self.assertGreaterEqual(
            self.results["swarm_consensus"],
            self.results["majority_vote"] - 0.02,
            "Trust-weighted swarm should match or beat unweighted majority",
        )

    def test_all_agents_above_random(self):
        for agent_id, acc in self.results["agent_accuracies"].items():
            self.assertGreater(
                acc, 0.50,
                f"Agent {agent_id} should be above random (50%)",
            )


class TestSwarmWithDiverseAccuracies(unittest.TestCase):
    """Swarm with diverse agent accuracies still outperforms."""

    def test_swarm_with_one_weak_agent(self):
        agents = [
            AgentProfile("strong-1", base_accuracy=0.70, trust=1.5),
            AgentProfile("strong-2", base_accuracy=0.65, trust=1.3),
            AgentProfile("medium", base_accuracy=0.58, trust=1.0),
            AgentProfile("weak", base_accuracy=0.45, trust=0.5),  # Below random
        ]
        scenarios = generate_scenarios(500, seed=99)
        results = run_benchmark(agents, scenarios, seed=99)

        # Swarm should still beat the weak agent
        self.assertGreater(
            results["swarm_consensus"],
            results["agent_accuracies"]["weak"],
        )
        # Swarm should be above 55%
        self.assertGreater(results["swarm_consensus"], 0.55)

    def test_swarm_with_all_mediocre_agents(self):
        agents = [
            AgentProfile(f"agent-{i}", base_accuracy=0.55, trust=1.0)
            for i in range(5)
        ]
        scenarios = generate_scenarios(500, seed=77)
        results = run_benchmark(agents, scenarios, seed=77)

        # Even mediocre agents pooled should beat random
        self.assertGreater(results["swarm_consensus"], 0.52)


class TestTrustWeightingEffect(unittest.TestCase):
    """Higher trust on better agents should improve swarm accuracy."""

    def test_trust_weighting_helps(self):
        # Agents with correct trust assignment
        good_trust_agents = [
            AgentProfile("best", base_accuracy=0.70, trust=2.0),
            AgentProfile("good", base_accuracy=0.60, trust=1.5),
            AgentProfile("ok", base_accuracy=0.55, trust=1.0),
            AgentProfile("weak", base_accuracy=0.48, trust=0.5),
        ]
        # Same agents with inverted (wrong) trust
        bad_trust_agents = [
            AgentProfile("best", base_accuracy=0.70, trust=0.5),
            AgentProfile("good", base_accuracy=0.60, trust=1.0),
            AgentProfile("ok", base_accuracy=0.55, trust=1.5),
            AgentProfile("weak", base_accuracy=0.48, trust=2.0),
        ]

        scenarios = generate_scenarios(500, seed=55)
        good_results = run_benchmark(good_trust_agents, scenarios, seed=55)
        bad_results = run_benchmark(bad_trust_agents, scenarios, seed=55)

        # Correct trust weighting should outperform inverted trust
        self.assertGreater(
            good_results["swarm_consensus"],
            bad_results["swarm_consensus"],
            "Correct trust weighting should outperform inverted trust",
        )


class TestLargeScenarioStability(unittest.TestCase):
    """Results should be stable across large scenario counts."""

    def test_1000_scenarios_stable(self):
        scenarios = generate_scenarios(1000, seed=123)
        r1 = run_benchmark(DEFAULT_AGENTS, scenarios, seed=123)
        r2 = run_benchmark(DEFAULT_AGENTS, scenarios, seed=123)

        # Same seed → same results
        self.assertAlmostEqual(
            r1["swarm_consensus"],
            r2["swarm_consensus"],
            places=10,
        )

    def test_swarm_accuracy_above_60_on_1000(self):
        scenarios = generate_scenarios(1000, seed=456)
        results = run_benchmark(DEFAULT_AGENTS, scenarios, seed=456)
        self.assertGreater(
            results["swarm_consensus"], 0.60,
            "Swarm should achieve >60% on 1000 scenarios",
        )


class TestBenchmarkOutputStructure(unittest.TestCase):
    """Benchmark output has expected keys and value ranges."""

    def test_output_keys(self):
        scenarios = generate_scenarios(100, seed=1)
        results = run_benchmark(DEFAULT_AGENTS, scenarios, seed=1)
        expected_keys = {
            "swarm_consensus", "majority_vote", "best_single_agent",
            "worst_single_agent", "random_baseline", "agent_accuracies",
        }
        self.assertEqual(set(results.keys()), expected_keys)

    def test_accuracies_in_range(self):
        scenarios = generate_scenarios(100, seed=2)
        results = run_benchmark(DEFAULT_AGENTS, scenarios, seed=2)
        for key in ["swarm_consensus", "majority_vote", "best_single_agent",
                     "worst_single_agent", "random_baseline"]:
            self.assertGreaterEqual(results[key], 0.0)
            self.assertLessEqual(results[key], 1.0)

    def test_agent_accuracies_count(self):
        scenarios = generate_scenarios(100, seed=3)
        results = run_benchmark(DEFAULT_AGENTS, scenarios, seed=3)
        self.assertEqual(len(results["agent_accuracies"]), len(DEFAULT_AGENTS))


# ── Historical / realistic Kalshi benchmark (S1-04) ─────────────────


def generate_kalshi_scenarios(n: int, seed: int = 99) -> List[MarketScenario]:
    """Generate realistic Kalshi-style binary event scenarios.

    Simulates prediction market events with:
    - yes_ask / no_ask cent prices (1-99)
    - Implied probability from market mid
    - Known resolution (+1 = YES, -1 = NO)
    - Edge cases: tight spreads, wide spreads, extreme prices
    """
    rng = random.Random(seed)
    scenarios = []
    for i in range(n):
        # True probability of YES outcome
        true_prob = rng.betavariate(2, 2)  # beta(2,2) gives realistic distribution
        resolved_yes = rng.random() < true_prob
        true_signal = +1 if resolved_yes else -1

        # Market prices with noise around true probability
        # CRITICAL FIX: Updated to use [15, 70] range to prevent $0.99 purchases
        noise = rng.gauss(0, 0.08)
        yes_ask = max(15, min(70, int((true_prob + noise) * 100)))
        no_ask = max(15, min(70, 100 - yes_ask + rng.randint(-3, 3)))
        spread = abs(yes_ask + no_ask - 100)

        scenarios.append(MarketScenario(
            scenario_id=f"kalshi-{i:04d}",
            true_signal=true_signal,
            features={
                "yes_ask": float(yes_ask),
                "no_ask": float(no_ask),
                "implied_prob": yes_ask / 100.0,
                "spread_cents": float(spread),
                "volume": rng.lognormvariate(6, 1.5),
                "hours_to_expiry": rng.expovariate(1 / 24) + 0.5,
            },
        ))
    return scenarios


class TestHistoricalKalshiBenchmark(unittest.TestCase):
    """Benchmark swarm consensus on realistic Kalshi-style event data."""

    def setUp(self):
        self.agents = DEFAULT_AGENTS
        self.scenarios = generate_kalshi_scenarios(500, seed=99)

    def test_kalshi_swarm_beats_random(self):
        results = run_benchmark(self.agents, self.scenarios, seed=99)
        self.assertGreater(
            results["swarm_consensus"],
            results["random_baseline"] + 0.03,
            "Swarm should beat random by >3% on Kalshi-style scenarios",
        )

    def test_kalshi_swarm_beats_worst_agent(self):
        results = run_benchmark(self.agents, self.scenarios, seed=99)
        self.assertGreater(
            results["swarm_consensus"],
            results["worst_single_agent"],
            "Swarm should beat worst single agent on Kalshi scenarios",
        )

    def test_kalshi_swarm_within_5pct_of_best(self):
        results = run_benchmark(self.agents, self.scenarios, seed=99)
        gap = results["best_single_agent"] - results["swarm_consensus"]
        self.assertLessEqual(
            gap, 0.05,
            f"Swarm should be within 5% of best agent (gap={gap:.3f})",
        )

    def test_kalshi_scenario_features_valid(self):
        for s in self.scenarios[:50]:
            self.assertIn(s.true_signal, (+1, -1))
            self.assertGreaterEqual(s.features["yes_ask"], 1)
            self.assertLessEqual(s.features["yes_ask"], 99)
            self.assertGreater(s.features["volume"], 0)
            self.assertGreater(s.features["hours_to_expiry"], 0)

    def test_kalshi_1000_scenarios_accuracy_above_55(self):
        scenarios = generate_kalshi_scenarios(1000, seed=200)
        results = run_benchmark(self.agents, scenarios, seed=200)
        self.assertGreater(
            results["swarm_consensus"], 0.55,
            "Swarm should achieve >55% on 1000 Kalshi scenarios",
        )


if __name__ == "__main__":
    unittest.main()
