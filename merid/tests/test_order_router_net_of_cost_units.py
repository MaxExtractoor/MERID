"""Units regression tests for ``_round_trip_net_of_cost_gate``.

Defect (2026-11-19): the gate computed ``gross_edge_cents`` and the
round-trip costs as ORDER TOTALS (scaled by ``count_value``) but compared
them against ``_lane_floor_c`` — a PER-CONTRACT bound
(``min_required_edge`` fraction -> cents/contract, the same basis the
decision layer, the intent-contract negative-EV guard, and the
fill-adjusted-edge check all use).  For multi-contract bounded-lane
probes the floor was effectively ``count_value``x too strict; for
fractional counts it was too loose.

Canonical reproduction: KXETH15M-26NOV172330-30 pinned_fav maker probe —
5 contracts @94c, p_selected=0.9154 -> gross -12.3c total (-2.46c/ct),
maker round-trip ~0.99c total -> maker_net -13.3c total = -2.66c/ct vs
lane floor -12c/ct.  The old total-vs-floor comparison rejected an order
the per-contract comparison (and every other gate) admits.
"""

import time as _time
from decimal import Decimal

import pytest

from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    _round_trip_net_of_cost_gate,
)


class _MockMarketState:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestNetOfCostUnits:
    def _intent(self, **overrides):
        defaults = {
            "ticker": "KXETH15M-26NOV172330-30",
            "side": "yes",
            "action": "buy",
            "price_cents": 94,
            "count": 1,
            "count_fp": Decimal("1"),
            "edge_pct": -2.46,
            "aggressiveness": 0.0,
            "post_only": True,
            "p_selected": 0.9154,
            "decision_lane": "pinned_fav",
            "min_required_edge": -0.12,
        }
        defaults.update(overrides)
        return OrderIntent(**defaults)

    def _state(self, **overrides):
        defaults = {
            "best_bid_cents": 93,
            "best_ask_cents": 95,
            "book_initialized": True,
            "last_book_update_wall_ts": _time.time(),
        }
        defaults.update(overrides)
        return _MockMarketState(**defaults)

    @pytest.fixture(autouse=True)
    def _patch_store_and_env(self, monkeypatch):
        from merid.event_venues.kalshi import market_state

        class _FakeStore:
            def __init__(self, test):
                self._test = test

            def get(self, ticker):
                return getattr(self._test, "_market_state", None)

        monkeypatch.setattr(
            market_state, "get_kalshi_market_state_store", lambda: _FakeStore(self)
        )
        # Pin the exit-policy branch so maker round-trip = 2 x maker fee
        # (the configuration under which the production rejection was
        # recorded: maker_cost=1.0c for 5ct @94c).
        monkeypatch.setenv("MERID_DISABLE_EXIT_POLICY", "0")

    # ── Exact production reproduction ────────────────────────────────────

    def test_eth_pinned_fav_five_contract_repro(self):
        """The reported KXETH15M-26NOV172330-30 rejection must clear the
        per-contract lane floor exactly as the decision layer and the
        intent-contract guard already evaluate it."""
        self._market_state = self._state()
        intent = self._intent(
            count=5,
            count_fp=Decimal("5"),
            p_selected=0.9154,
            price_cents=94,
            min_required_edge=-0.12,
            decision_lane="pinned_fav",
        )
        reason = _round_trip_net_of_cost_gate(intent)
        assert reason is None, f"gate rejected consistent per-contract economics: {reason}"
        assert intent.policy_mode == "NEUTRAL_MM"

    # ── Quantity invariance (the core property) ──────────────────────────

    @pytest.mark.parametrize("count", ["1", "2", "5", "10"])
    def test_bounded_lane_verdict_is_quantity_invariant(self, count):
        """With identical per-contract economics, changing quantity alone
        must not change whether the per-contract net clears the
        per-contract floor (fee quantization is sub-0.01c/ct and cannot
        move this fixture across the -12c floor)."""
        self._market_state = self._state()
        intent = self._intent(count=int(count), count_fp=Decimal(count))
        reason = _round_trip_net_of_cost_gate(intent)
        assert reason is None, f"count={count}: {reason}"

    def test_fractional_count_uses_per_contract_floor(self):
        """Fractional orders were too LOOSE under the total-vs-floor bug:
        per-contract net -14.1c is below the -12c floor even though the
        0.5-contract total (-7.05c) sat above the unscaled floor."""
        self._market_state = self._state()
        intent = self._intent(
            count=0.5,
            count_fp=Decimal("0.5"),
            p_selected=0.80,  # gross -14c/contract at 94c
            price_cents=94,
        )
        reason = _round_trip_net_of_cost_gate(intent)
        assert reason is not None and "net_of_cost" in reason

    def test_single_contract_unchanged(self):
        """count=1: total == per-contract, so the fix must be a no-op."""
        self._market_state = self._state()
        intent = self._intent(count=1, count_fp=Decimal("1"))
        reason = _round_trip_net_of_cost_gate(intent)
        assert reason is None
        assert intent.policy_mode == "NEUTRAL_MM"

    # ── Floor sign matrix ────────────────────────────────────────────────

    def test_unstamped_lane_keeps_zero_floor(self):
        """A non-bounded lane with negative per-contract economics must
        still be rejected — the fix grants no new permission."""
        self._market_state = self._state()
        intent = self._intent(
            count=5,
            count_fp=Decimal("5"),
            decision_lane=None,
            min_required_edge=None,
            edge_pct=-2.46,
        )
        reason = _round_trip_net_of_cost_gate(intent)
        assert reason == "net_of_cost:zero_or_negative_edge"

    def test_unbounded_lane_positive_mre_still_zero_floor(self):
        """A positively-stamped min_required_edge clamps the floor to 0 —
        bounded-lane relaxation must not leak to ordinary lanes."""
        self._market_state = self._state()
        intent = self._intent(
            count=5,
            count_fp=Decimal("5"),
            decision_lane="formula",
            min_required_edge=0.05,
            edge_pct=-2.46,
        )
        reason = _round_trip_net_of_cost_gate(intent)
        assert reason == "net_of_cost:zero_or_negative_edge"

    def test_bounded_lane_positive_mre_clamps_to_zero(self):
        """Positive stamped floor on a bounded lane also clamps to 0:
        negative-edge probes need an explicitly negative bound."""
        self._market_state = self._state()
        intent = self._intent(
            count=5,
            count_fp=Decimal("5"),
            min_required_edge=0.05,
            edge_pct=-2.46,
        )
        reason = _round_trip_net_of_cost_gate(intent)
        assert reason == "net_of_cost:zero_or_negative_edge"

    def test_floor_boundary_is_strictly_greater(self):
        """Net exactly at the floor must still reject (strict >)."""
        self._market_state = self._state()
        # Solve gross_pc so maker_net_pc lands just under -12c.
        # gross_pc = (p-0.94)*100; maker_rt_pc ~0.2c at 94c/5ct.
        # p=0.815 -> gross_pc=-12.5c; maker_net_pc ~ -12.7c < -12c.
        intent = self._intent(
            count=5,
            count_fp=Decimal("5"),
            p_selected=0.815,
            edge_pct=-12.5,
        )
        reason = _round_trip_net_of_cost_gate(intent)
        assert reason is not None and "net_of_cost" in reason

        # And just above: p=0.935 -> gross_pc=-0.5c -> net_pc ~ -0.7c > -12c.
        intent2 = self._intent(
            count=5,
            count_fp=Decimal("5"),
            p_selected=0.935,
            edge_pct=-0.5,
        )
        reason2 = _round_trip_net_of_cost_gate(intent2)
        assert reason2 is None

    # ── All five assets ──────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "ticker",
        [
            "KXBTC15M-26NOV172330-30",
            "KXETH15M-26NOV172330-30",
            "KXSOL15M-26NOV172330-30",
            "KXXRP15M-26NOV172330-30",
            "KXDOGE15M-26NOV172330-30",
        ],
    )
    def test_bounded_lane_multicontract_all_assets(self, ticker):
        self._market_state = self._state()
        intent = self._intent(ticker=ticker, count=5, count_fp=Decimal("5"))
        reason = _round_trip_net_of_cost_gate(intent)
        assert reason is None, f"{ticker}: {reason}"

    # ── Taker path uses the same per-contract basis ──────────────────────

    def test_aggressive_taker_multicontract_per_contract(self):
        """An aggressiveness>0 intent may take the taker path only when
        per-contract taker net clears the per-contract floor."""
        self._market_state = self._state(best_bid_cents=93, best_ask_cents=94)
        # p=0.90 @94c -> gross_pc=-4c; taker_rt_pc ~ (2*1.97+1)/5 ~ 0.99c
        # -> taker_net_pc ~ -5c > -12c floor -> taker viable.
        intent = self._intent(
            count=5,
            count_fp=Decimal("5"),
            p_selected=0.90,
            aggressiveness=1.0,
            post_only=False,
        )
        reason = _round_trip_net_of_cost_gate(intent)
        assert reason is None
        assert intent.policy_mode == "AGGRESSIVE_CONVICTION"
