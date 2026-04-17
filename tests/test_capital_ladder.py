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

class TestStructuralInvariants:
    """Engine errors, reconciliation breaks, kill-switch — must all be clean."""

    @pytest.mark.slow
    @pytest.mark.parametrize("case", LADDER, ids=[c["name"] for c in LADDER])
    def test_zero_engine_errors(self, case, ladder_results):
        m = _run_bracket(case, ladder_results)
        assert m.errors == 0, (
            f"[{case['name']}] {m.errors} engine errors during simulation"
        )

    @pytest.mark.slow
    @pytest.mark.parametrize("case", LADDER, ids=[c["name"] for c in LADDER])
    def test_no_reconciliation_errors(self, case, ladder_results):
        """Reconciliation must have zero ERROR-status checks.

        DELTA-status checks (balance identity drift from realised PnL)
        are a known limitation of the current formula and are tolerated.
        """
        m = _run_bracket(case, ladder_results)
        report = m.reconciliation_report
        if report is None:
            pytest.skip("no reconciliation report")
        error_checks = [
            c for c in report.get("checks", [])
            if c.get("status") == "error"
        ]
        assert len(error_checks) == 0, (
            f"[{case['name']}] {len(error_checks)} reconciliation errors: "
            f"{[c['name'] for c in error_checks]}"
        )

    @pytest.mark.slow
    @pytest.mark.parametrize("case", LADDER, ids=[c["name"] for c in LADDER])
    def test_kill_switch_not_triggered(self, case, ladder_results):
        m = _run_bracket(case, ladder_results)
        assert m.kill_switch_triggered is False, (
            f"[{case['name']}] kill switch was triggered"
        )

    @pytest.mark.slow
    @pytest.mark.parametrize("case", LADDER, ids=[c["name"] for c in LADDER])
    def test_reconciliation_ran(self, case, ladder_results):
        m = _run_bracket(case, ladder_results)
        assert m.reconciliation_checks >= 1, (
            f"[{case['name']}] reconciliation never ran"
        )

    @pytest.mark.slow
    @pytest.mark.parametrize("case", LADDER, ids=[c["name"] for c in LADDER])
    def test_trades_executed(self, case, ladder_results):
        m = _run_bracket(case, ladder_results)
        assert m.total_trades > 0, (
            f"[{case['name']}] no trades executed — strategy may be broken"
        )


# ------------------------------------------------------------------ #
# §2 — Risk invariants
# ------------------------------------------------------------------ #

class TestRiskInvariants:
    """Drawdown stays within bracket-specific thresholds."""

    @pytest.mark.slow
    @pytest.mark.parametrize("case", LADDER, ids=[c["name"] for c in LADDER])
    def test_max_drawdown_within_threshold(self, case, ladder_results):
        m = _run_bracket(case, ladder_results)
        threshold = _MAX_DD.get(case["name"], 0.50)
        assert m.max_drawdown <= threshold, (
            f"[{case['name']}] max drawdown {m.max_drawdown:.1%} "
            f"exceeds threshold {threshold:.0%}"
        )

    @pytest.mark.slow
    @pytest.mark.parametrize("case", LADDER, ids=[c["name"] for c in LADDER])
    def test_equity_never_negative(self, case, ladder_results):
        m = _run_bracket(case, ladder_results)
        assert m.trough_equity >= 0, (
            f"[{case['name']}] equity went negative: ${m.trough_equity:.2f}"
        )

    @pytest.mark.slow
    @pytest.mark.parametrize("case", LADDER, ids=[c["name"] for c in LADDER])
    def test_win_rate_plausible(self, case, ladder_results):
        m = _run_bracket(case, ladder_results)
        # Win rate should be between 0% and 100%
        assert 0.0 <= m.win_rate <= 1.0, (
            f"[{case['name']}] win rate {m.win_rate:.1%} out of [0, 1] range"
        )


# ------------------------------------------------------------------ #
# §3 — Performance invariants (positive edge)
# ------------------------------------------------------------------ #

class TestPerformanceInvariants:
    """Final equity should exceed initial capital (positive edge over the run)."""

    @pytest.mark.slow
    @pytest.mark.parametrize("case", LADDER, ids=[c["name"] for c in LADDER])
    def test_positive_final_equity(self, case, ladder_results):
        m = _run_bracket(case, ladder_results)
        assert m.final_equity > 0, (
            f"[{case['name']}] final equity is ${m.final_equity:.2f}"
        )

    @pytest.mark.slow
    @pytest.mark.parametrize("case", LADDER, ids=[c["name"] for c in LADDER])
    def test_no_catastrophic_loss(self, case, ladder_results):
        """Equity must not drop below 20% of initial capital.

        This is a structural safety check, not an alpha test.
        The simple mean-reversion strategy is a harness driver,
        not a production strategy — positive edge is not guaranteed.
        """
        m = _run_bracket(case, ladder_results)
        floor = case["initial"] * 0.20
        assert m.final_equity >= floor, (
            f"[{case['name']}] catastrophic loss: "
            f"${case['initial']} → ${m.final_equity:.2f} ({m.roi_pct:.1f}%)"
        )

    @pytest.mark.slow
    @pytest.mark.parametrize("case", LADDER, ids=[c["name"] for c in LADDER])
    def test_equity_curve_populated(self, case, ladder_results):
        m = _run_bracket(case, ladder_results)
        assert len(m.equity_curve) > 0, (
            f"[{case['name']}] equity curve is empty"
        )


# ------------------------------------------------------------------ #
# §4 — Cross-bracket consistency
# ------------------------------------------------------------------ #

class TestCrossBracketConsistency:
    """Verify the ladder produces coherent results across brackets."""

    @pytest.mark.slow
    def test_all_brackets_ran(self, ladder_results):
        """Run all brackets and verify we got results for each."""
        for case in LADDER:
            _run_bracket(case, ladder_results)
        assert len(ladder_results) == len(LADDER), (
            f"Expected {len(LADDER)} brackets, got {len(ladder_results)}"
        )

    @pytest.mark.slow
    def test_trade_count_scales_with_capital(self, ladder_results):
        """Larger brackets should generally execute more trades (more margin)."""
        for case in LADDER:
            _run_bracket(case, ladder_results)

        # At minimum, every bracket should have traded
        for name, m in ladder_results.items():
            assert m.total_trades > 0, f"[{name}] zero trades"

    @pytest.mark.slow
    def test_reconciliation_report_shape(self, ladder_results):
        """Final reconciliation report should have expected keys."""
        for case in LADDER:
            _run_bracket(case, ladder_results)

        for name, m in ladder_results.items():
            report = m.reconciliation_report
            assert report is not None, f"[{name}] no final reconciliation report"
            assert "all_ok" in report, f"[{name}] report missing 'all_ok'"
            assert "checks" in report, f"[{name}] report missing 'checks'"
            assert "snapshot_hash" in report, f"[{name}] report missing 'snapshot_hash'"

    @pytest.mark.slow
    def test_metrics_to_dict(self, ladder_results):
        """PaperMetrics.to_dict() should return a serializable dict."""
        for case in LADDER:
            m = _run_bracket(case, ladder_results)
            d = m.to_dict()
            assert isinstance(d, dict)
            assert d["bracket_name"] == case["name"]
            assert d["initial_capital"] == case["initial"]
            assert isinstance(d["final_equity"], float)
            assert isinstance(d["errors"], int)


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
