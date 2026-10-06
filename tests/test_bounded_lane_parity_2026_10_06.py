"""Regression tests for bounded-lane WINNER_MISMATCH false vetoes (2026-10-06).

Incident: KXDOGE15M-26OCT061700-00 chose NO via the evidence_cell_escape lane
(resting 54c NO bid) while the book was yes 34/35 x no 65/66 and model p_yes
was 0.3934.  Mid-space edges (+4.84c / -4.84c) are exact mirrors by
construction, so the parity WINNER_MISMATCH check vetoed the order — it
compared the lane's executable-basis pick against midpoint argmax, a
different price space.

The fix reprices parity edges to each side's lane-executable basis:
the chosen side at its submitted limit, the alternate at its maker-postable
bid (or ask for taker roles).  A true side inversion still fails.
"""

import pytest

from merid.prediction.canonical_edge import (
    compute_canonical_edges,
    repriced_parity_edges,
)
from merid.validation.yes_no_parity_checker import (
    BotView,
    ExecutionDecision,
    ExposureIntent,
    IntendedAction,
    MarketSnapshot,
    YesNoParityChecker,
)


# ---------------------------------------------------------------------------
# DOGE incident fixture values (2026-10-06 16:49:18)
# ---------------------------------------------------------------------------
DOG = dict(
    yes_bid=34, yes_ask=35, no_bid=65, no_ask=66,
    p_yes=0.39338699999999993,
    no_limit=54,  # resting maker bid the lane submitted (api_no_price=0.54)
)


class TestRepricedParityEdges:
    """repriced_parity_edges evaluates the winner check in executable space."""

    def test_doge_no_pick_passes_at_limit_price(self):
        """NO maker pick at 54c: chosen edge +6.66c vs alt-YES maker edge +5.34c."""
        edge_yes, edge_no = repriced_parity_edges(
            chosen_side="no",
            model_prob_yes=DOG["p_yes"],
            limit_price_frac=DOG["no_limit"] / 100.0,
            yes_bid_cents=DOG["yes_bid"],
            yes_ask_cents=DOG["yes_ask"],
            no_bid_cents=DOG["no_bid"],
            no_ask_cents=DOG["no_ask"],
            liquidity_role="maker",
            fallback_edge_yes=0.0484,
            fallback_edge_no=-0.0484,
        )
        assert edge_no == pytest.approx(0.6066 - 0.54, abs=1e-3)
        assert edge_yes == pytest.approx(0.3934 - 0.34, abs=1e-3)
        assert edge_no > edge_yes  # NO wins in executable space

    def test_true_side_inversion_still_fails(self):
        """If the lane 'chose NO' but NO's limit edge is negative while a
        YES maker bid is positive, the winner check must still fire."""
        # Same book/model but the submitted NO limit is 62c -> edge -1.34c,
        # while YES at bid gives +5.34c.  That is a genuine wrong-side pick.
        edge_yes, edge_no = repriced_parity_edges(
            chosen_side="no",
            model_prob_yes=DOG["p_yes"],
            limit_price_frac=0.62,
            yes_bid_cents=DOG["yes_bid"],
            yes_ask_cents=DOG["yes_ask"],
            no_bid_cents=DOG["no_bid"],
            no_ask_cents=DOG["no_ask"],
            liquidity_role="maker",
            fallback_edge_yes=0.0484,
            fallback_edge_no=-0.0484,
        )
        assert edge_no == pytest.approx(0.6066 - 0.62, abs=1e-3)
        assert edge_yes > edge_no  # YES wins -> WINNER_MISMATCH preserved

    def test_taker_role_uses_alternate_ask(self):
        """Taker alternates pay the ask, not the bid."""
        edge_yes, edge_no = repriced_parity_edges(
            chosen_side="no",
            model_prob_yes=DOG["p_yes"],
            limit_price_frac=0.54,
            yes_bid_cents=DOG["yes_bid"],
            yes_ask_cents=DOG["yes_ask"],
            no_bid_cents=DOG["no_bid"],
            no_ask_cents=DOG["no_ask"],
            liquidity_role="taker",
            fallback_edge_yes=0.0484,
            fallback_edge_no=-0.0484,
        )
        assert edge_yes == pytest.approx(0.3934 - 0.35, abs=1e-3)  # yes_ask

    def test_missing_alt_book_falls_back(self):
        """Missing book data returns the caller's fallback edges unchanged."""
        out = repriced_parity_edges(
            chosen_side="no",
            model_prob_yes=DOG["p_yes"],
            limit_price_frac=0.54,
            yes_bid_cents=None,
            yes_ask_cents=None,
            no_bid_cents=DOG["no_bid"],
            no_ask_cents=DOG["no_ask"],
            liquidity_role="maker",
            fallback_edge_yes=0.0484,
            fallback_edge_no=-0.0484,
        )
        assert out == (0.0484, -0.0484)

    def test_missing_side_or_prob_falls_back(self):
        for side, prob in [("none", 0.4), (None, 0.4), ("no", None)]:
            out = repriced_parity_edges(
                chosen_side=side,
                model_prob_yes=prob,
                limit_price_frac=0.54,
                yes_bid_cents=DOG["yes_bid"],
                yes_ask_cents=DOG["yes_ask"],
                no_bid_cents=DOG["no_bid"],
                no_ask_cents=DOG["no_ask"],
                liquidity_role="maker",
                fallback_edge_yes=0.01,
                fallback_edge_no=-0.01,
            )
            assert out == (0.01, -0.01)


class TestParityCheckerWithRepricedEdges:
    """End-to-end: checker sees executable-basis edges for bounded lanes."""

    def _checker(self):
        return YesNoParityChecker()

    def _snapshot(self):
        return MarketSnapshot(
            market_id="KXDOGE15M-26OCT061700-00",
            asset="DOGE",
            expiry_ts=0,
            yes_bid=DOG["yes_bid"], yes_ask=DOG["yes_ask"],
            no_bid=DOG["no_bid"], no_ask=DOG["no_ask"],
        )

    def _decision(self, side="no", price=0.54):
        return ExecutionDecision(
            intended_action=IntendedAction.BUY_NO if side == "no" else IntendedAction.BUY_YES,
            api_side=side,
            api_yes_price=price if side == "yes" else None,
            api_no_price=price if side == "no" else None,
        )

    def test_doge_case_passes_with_repriced_edges(self):
        """The exact incident: mid edges vetoed, repriced edges pass."""
        mid_yes, mid_no = compute_canonical_edges(
            model_prob_yes=DOG["p_yes"],
            market_price_yes=0.345,
            market_price_no=0.655,
        )
        # Sanity: mid edges are what produced the false veto
        assert mid_yes > mid_no

        rep_yes, rep_no = repriced_parity_edges(
            chosen_side="no", model_prob_yes=DOG["p_yes"],
            limit_price_frac=0.54,
            yes_bid_cents=DOG["yes_bid"], yes_ask_cents=DOG["yes_ask"],
            no_bid_cents=DOG["no_bid"], no_ask_cents=DOG["no_ask"],
            liquidity_role="maker",
            fallback_edge_yes=mid_yes, fallback_edge_no=mid_no,
        )
        view = BotView(
            model_prob_yes=DOG["p_yes"], model_prob_no=1.0 - DOG["p_yes"],
            edge_yes=rep_yes, edge_no=rep_no,
            chosen_side="no", exposure_intent=ExposureIntent.BEARISH_EVENT,
        )
        result = self._checker().check(self._snapshot(), view, self._decision())
        assert result.ok, f"false WINNER_MISMATCH veto recurred: {result.reasons}"

    def test_mid_edges_still_catch_real_mismatch(self):
        """Non-bounded candidates keep mid-space enforcement."""
        view = BotView(
            model_prob_yes=DOG["p_yes"], model_prob_no=1.0 - DOG["p_yes"],
            edge_yes=0.0484, edge_no=-0.0484,
            chosen_side="no", exposure_intent=ExposureIntent.BEARISH_EVENT,
        )
        result = self._checker().check(self._snapshot(), view, self._decision())
        assert not result.ok
        assert any("WINNER_MISMATCH" in r for r in result.reasons)

    def test_bounded_yes_pick_at_limit_passes(self):
        """Symmetric case: deep YES bid not vetoed when it wins executable space."""
        # Mid leans NO (p_yes below mid) but a resting 20c YES bid has
        # edge 0.30-0.20=+0.10 vs a NO maker bid 0.70-0.65=+0.05 -> YES wins.
        p_yes = 0.30
        mid_yes = 0.34
        rep_yes, rep_no = repriced_parity_edges(
            chosen_side="yes", model_prob_yes=p_yes,
            limit_price_frac=0.20,
            yes_bid_cents=33, yes_ask_cents=35,
            no_bid_cents=65, no_ask_cents=67,
            liquidity_role="maker",
            fallback_edge_yes=p_yes - mid_yes,
            fallback_edge_no=(1 - p_yes) - (1 - mid_yes),
        )
        assert rep_yes > rep_no
        view = BotView(
            model_prob_yes=p_yes, model_prob_no=1 - p_yes,
            edge_yes=rep_yes, edge_no=rep_no,
            chosen_side="yes", exposure_intent=ExposureIntent.BULLISH_EVENT,
        )
        result = self._checker().check(
            self._snapshot(), view, self._decision(side="yes", price=0.20)
        )
        assert result.ok, f"YES maker pick vetoed: {result.reasons}"
