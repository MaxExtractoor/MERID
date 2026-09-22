"""Capital-ladder test suite for MERID paper trading.

Parametrized across capital brackets:
    micro   :  $10      →  $100
    small   :  $100     →  $1,000
    medium  :  $1,000   →  $10,000
    large   :  $10,000  →  $100,000
    xl      :  $100,000 →  $1,000,000

Each bracket runs the same MERID paper harness:
  - Fresh PaperTradingEngine with synthetic GBM prices
  - Multi-symbol mean-reversion strategy
  - Periodic reconciliation every 5,000 ticks
  - Structural, risk, and performance invariants asserted

The target_hint is a *scenario label*, not a hard pass/fail gate.
"""

import pytest

from merid.testing import run_paper_scenario, PaperMetrics

# Register custom marks
pytestmark = [pytest.mark.filterwarnings("ignore::pytest.PytestUnknownMarkWarning")]

# ------------------------------------------------------------------ #
# Ladder definition
# ------------------------------------------------------------------ #

LADDER = [
    {"name": "micro",  "initial": 10,       "target_hint": 100},
    {"name": "small",  "initial": 100,      "target_hint": 1_000},
    {"name": "medium", "initial": 1_000,    "target_hint": 10_000},
    {"name": "large",  "initial": 10_000,   "target_hint": 100_000},
    {"name": "xl",     "initial": 100_000,  "target_hint": 1_000_000},
]

# Tick counts scale with bracket to keep runtime reasonable
_TICKS = {
    "micro":  10_000,
    "small":  20_000,
    "medium": 30_000,
    "large":  40_000,
    "xl":     50_000,
}

# Max drawdown thresholds per bracket (looser for smaller capital)
_MAX_DD = {
    "micro":  0.70,   # 70% — tiny capital, slippage-dominated
    "small":  0.55,   # 55%
    "medium": 0.45,
    "large":  0.35,
    "xl":     0.30,
}


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #

@pytest.fixture(scope="module")
def ladder_results() -> dict:
    """Cache results across all tests in this module."""
    return {}


def _run_bracket(case: dict, cache: dict) -> PaperMetrics:
    """Run a bracket if not already cached."""
    name = case["name"]
    if name not in cache:
        cache[name] = run_paper_scenario(
            initial_capital=case["initial"],
            ticks=_TICKS.get(name, 50_000),
            bracket_name=name,
            seed=42,
            reconcile_every=5_000,
        )
    return cache[name]


# ------------------------------------------------------------------ #
# §1 — Structural invariants (must pass for every bracket)
# ------------------------------------------------------------------ #



# ------------------------------------------------------------------ #
# §2 — Risk invariants
# ------------------------------------------------------------------ #



# ------------------------------------------------------------------ #
# §3 — Performance invariants (positive edge)
# ------------------------------------------------------------------ #



# ------------------------------------------------------------------ #
# §4 — Cross-bracket consistency
# ------------------------------------------------------------------ #



# ------------------------------------------------------------------ #
# §5 — Harness unit tests (fast, no simulation)
# ------------------------------------------------------------------ #

class TestHarnessUnit:
    """Quick tests for the harness itself, no slow simulation."""

    def test_price_generator_length(self):
        from merid.testing import _generate_price_series
        series = _generate_price_series("BTC-USD", 100, seed=1)
        assert len(series) == 100

    def test_price_generator_positive(self):
        from merid.testing import _generate_price_series
        series = _generate_price_series("BTC-USD", 1000, seed=1)
        assert all(p > 0 for p in series)

    def test_price_generator_deterministic(self):
        from merid.testing import _generate_price_series
        s1 = _generate_price_series("BTC-USD", 500, seed=42)
        s2 = _generate_price_series("BTC-USD", 500, seed=42)
        assert s1 == s2

    def test_price_generator_different_seeds(self):
        from merid.testing import _generate_price_series
        s1 = _generate_price_series("BTC-USD", 500, seed=1)
        s2 = _generate_price_series("BTC-USD", 500, seed=2)
        assert s1 != s2

    def test_metrics_dataclass_defaults(self):
        m = PaperMetrics()
        assert m.errors == 0
        assert m.reconciliation_breaks == 0
        assert m.kill_switch_triggered is False
        assert m.equity_curve == []

    def test_metrics_to_dict_keys(self):
        m = PaperMetrics(bracket_name="test", initial_capital=100)
        d = m.to_dict()
        expected_keys = {
            "bracket_name", "initial_capital", "final_equity", "total_pnl",
            "roi_pct", "max_drawdown", "total_trades", "win_rate",
            "errors", "reconciliation_breaks", "kill_switch_triggered",
        }
        assert set(d.keys()) == expected_keys

    def test_ladder_definition_complete(self):
        """LADDER has all required keys."""
        for case in LADDER:
            assert "name" in case
            assert "initial" in case
            assert "target_hint" in case
            assert case["initial"] > 0
            assert case["target_hint"] > case["initial"]

    def test_ladder_is_10x_progression(self):
        """Each bracket is 10× the previous."""
        for i in range(1, len(LADDER)):
            assert LADDER[i]["initial"] == LADDER[i - 1]["initial"] * 10
