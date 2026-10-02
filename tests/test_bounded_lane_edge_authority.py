"""Bounded post-only lanes: downstream edge-authority + parity integrity tests.

Regression coverage for the 2026-10-01 fix: the 15m loop's parity/edge block
previously re-derived a pass/fail verdict from orderbook *midpoints* with a
second fee-aware threshold table, vetoing bounded-lane candidates that the
decision engine had already admitted on the *executable* price — e.g. an ETH
NO admitted at the 69c ask with +4.4c net EV was rejected when the gate
recomputed +2.4c against a 75.5c mid at a 4.0c required-edge table.

Bounded lanes carry authoritative executable-price economics and are re-gated
at the submitted price by evaluate_executable_cost_ev, so their decision side
is authoritative downstream.  Parity integrity checks (price parity,
WINNER_MISMATCH edge-argmax disagreement) must still apply.
"""

import inspect

import pytest

from merid.prediction.canonical_edge import (
    compute_canonical_edges,
    resolve_gate_side,
    select_winner_side,
)
from merid.prediction.trade_decision import BOUNDED_POST_ONLY_LANES
from merid.validation.yes_no_parity_checker import (
    BotView,
    ExecutionDecision,
    ExposureIntent,
    IntendedAction,
    MarketSnapshot,
    YesNoParityChecker,
)


class TestResolveGateSide:
    """Unit tests for the bounded-lane side-authority resolver."""

    def test_bounded_lane_survives_midpoint_below_threshold(self):
        """The ETH-NO@69 case: mid-recompute says 'none', lane side wins."""
        # Mid-price edges as the loop computed them: edge_no=+0.024 below a
        # 0.04 required threshold -> 'none'.  The lane already passed +4.4c
        # executable net EV, so the decision side is authoritative.
        side, deferred = resolve_gate_side("none", "no", True)
        assert side == "no"
        assert deferred is True

    def test_bounded_lane_recomputed_agreement_no_override_flag(self):
        side, deferred = resolve_gate_side("no", "no", True)
        assert side == "no"
        assert deferred is False

    def test_bounded_lane_opposite_mid_verdict_still_defers(self):
        """Mid-argmax disagreement defers to decision side; WINNER_MISMATCH
        remains the downstream guard for genuine side inversions."""
        side, deferred = resolve_gate_side("yes", "no", True)
        assert side == "no"
        assert deferred is True

    def test_primary_lane_none_stays_none(self):
        """Non-bounded candidates keep the midpoint verdict — the cents-edge
        gate still blocks the primary lane exactly as before."""
        side, deferred = resolve_gate_side("none", "no", False)
        assert side == "none"
        assert deferred is False

    def test_bounded_lane_invalid_side_fails_closed(self):
        """A lane candidate with an unresolvable side keeps 'none' — no
        authority is granted to a malformed order."""
        for bad in (None, "", "buy", "hold", "NOPE"):
            side, deferred = resolve_gate_side("none", bad, True)
            assert side == "none"
            assert deferred is False

    def test_bounded_lane_side_case_insensitive(self):
        side, deferred = resolve_gate_side("none", "YES", True)
        assert side == "yes"
        assert deferred is True


class TestBoundedLaneMembership:
    """The shared lane constant is the single source of truth."""

    def test_expected_lanes_present(self):
        assert BOUNDED_POST_ONLY_LANES == {
            "cheap_tail_canary",
            "evidence_cell_escape",
            "threshold_cell",
            "current_build_provisional",
            "trend_yes_hi",
            # 2026-10-02: queue-priced maker lane — admitted on bid-side
            # economics; stays inside the bounded post-only contract.
            "maker_bid",
        }


class TestWinnerMismatchStillBlocks:
    """Feeding the decision side into the parity checker must NOT neuter
    WINNER_MISMATCH: the checker compares chosen_side against the mid-edge
    argmax independently of how chosen_side was derived."""

    def _market(self):
        return MarketSnapshot(
            market_id="KXETH15M-T",
            asset="ETH",
            expiry_ts=1760000000,
            yes_bid=0.24,
            yes_ask=0.25,
            no_bid=0.75,
            no_ask=0.76,
        )

    def test_mismatch_fires_when_mid_edges_favor_other_side(self):
        checker = YesNoParityChecker(edge_eps=1e-3)
        v = BotView(
            model_prob_yes=0.55,
            model_prob_no=0.45,
            edge_yes=0.05,   # mid edge argmax says YES
            edge_no=-0.05,
            chosen_side="no",  # decision side overridden by lane authority
            exposure_intent=ExposureIntent.BEARISH_EVENT,
        )
        d = ExecutionDecision(
            intended_action=IntendedAction.BUY_NO,
            api_side="no",
            api_yes_price=None,
            api_no_price=0.755,
        )
        result = checker.check(self._market(), v, d)
        assert not result.ok
        assert any("WINNER_MISMATCH" in r for r in result.reasons)

    def test_consistent_side_passes(self):
        """The live ETH-NO@69 geometry: NO is the mid-argmax too."""
        checker = YesNoParityChecker(edge_eps=1e-3)
        edge_yes, edge_no = compute_canonical_edges(
            model_prob_yes=0.221,
            market_price_yes=0.245,
            market_price_no=0.755,
        )
        assert edge_no > edge_yes
        v = BotView(
            model_prob_yes=0.221,
            model_prob_no=0.779,
            edge_yes=edge_yes,
            edge_no=edge_no,
            chosen_side="no",
            exposure_intent=ExposureIntent.BEARISH_EVENT,
        )
        d = ExecutionDecision(
            intended_action=IntendedAction.BUY_NO,
            api_side="no",
            api_yes_price=None,
            api_no_price=0.755,
        )
        result = checker.check(self._market(), v, d)
        assert result.ok, f"unexpected failure: {result.reasons}"


class TestLoopWiringInvariants:
    """Source-level invariants mirroring the repo's existing test style —
    the gate must (a) resolve via resolve_gate_side and (b) keep the
    select_winner_side midpoint computation for diagnostics."""

    @pytest.fixture(scope="class")
    def loop_source(self):
        import merid.loop_15m as loop_mod
        return inspect.getsource(loop_mod)

    def test_resolve_gate_side_called_after_winner_selection(self, loop_source):
        sel_idx = loop_source.index("select_winner_side(")
        res_idx = loop_source.index("resolve_gate_side(")
        none_idx = loop_source.index('chosen_side == "none"')
        assert sel_idx < res_idx < none_idx, (
            "resolve_gate_side must sit between the midpoint winner selection "
            "and the none-block so bounded lanes defer to decision side"
        )

    def test_bounded_lanes_constant_imported(self, loop_source):
        assert "BOUNDED_POST_ONLY_LANES" in loop_source

    def test_no_silent_taker_coercion_for_bounded_lanes(self, loop_source):
        """Every bounded lane must route through the maker-disabled reject
        path rather than the coerce-to-IOC fallback."""
        import merid.loop_15m as loop_mod
        src = inspect.getsource(loop_mod)
        # The coercion block must gate on _is_bounded_lane, not per-lane names
        assert "elif _is_bounded_lane:" in src
        # Per-lane enablement resolvers exist for lanes without a maker switch
        assert "trend_yes_hi_enabled" in src
        assert "escape_lane_enabled" in src
        assert "MERID_CHEAP_TAIL_CANARY_ENABLED" in src


class TestAgentGridWiringInvariants:
    def test_order_style_conversion_uses_shared_constant(self):
        import merid.prediction.agent_grid_15m as grid
        src = inspect.getsource(grid)
        assert "_decision_lane in BOUNDED_POST_ONLY_LANES" in src
