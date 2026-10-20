"""Regression tests for the 2026-10-20 exit-floor / order-parse audit.

Live evidence driving these tests (KXBTC15M-26OCT192230-30, YES@78 entry):

- EDGE_DECAY fired at bid 74-76c (< entry 78c) three times and was
  suppressed by the breakeven floor because ``entry_edge`` /
  ``peak_price_cents`` were never wired into the stop-candidate-path
  ``loss_sell_blocked`` calls — only the exit-resolver path passed them.
- HARD_STOP fired at ~67c and was shadowed (by design).
- LOSS_CAP fired once at bid 47c, submitted an IOC at limit 44c, the book
  fell through 44 in ~1.5s, the IOC missed, ``tail_loss_floor_fired``
  latched forever, and the position settled ~0 (-78c).
- Every create-order response hit ORDER-PARSE-DEGRADED because Kalshi's
  create response omits action/book_side; the parse defaulted side='buy'
  on sells too.
"""

import os
import sys
import types
import unittest
from decimal import Decimal
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.event_venues.kalshi.stop_candidate import (
    StopCandidate,
    _candidate_floor_entry_edge,
    _stop_sweep_cents,
    loss_sell_blocked,
)
from merid.position_management.position_monitor import (
    _get_tail_loss_floor_config,
    _tail_floor_fire_allowed,
)


class _Pos:
    def __init__(self, **kw):
        self.tail_loss_floor_fired = kw.get("fired", False)
        self.tail_loss_floor_fired_at = kw.get("fired_at")
        self.tail_loss_floor_attempts = kw.get("attempts", 0)


class TestBreakevenFloorWiring(unittest.TestCase):
    """entry_edge / peak must reach the floor from the candidate path."""

    def setUp(self):
        os.environ.pop("MERID_PROFIT_ONLY_EXITS", None)

    def _cand(self, **kw):
        return StopCandidate(
            market_ticker="KXBTC15M-T",
            trigger_reason=kw.get("trigger", "EDGE_DECAY"),
            position_from_exchange_cc=100,
            entry_price_cents=kw.get("entry", 78),
            fair_value_cents=kw.get("fair", 74),
            executable_exit_cents=kw.get("bid", 74),
            entry_edge_cents=kw.get("edge", -4),
            peak_price_cents=kw.get("peak"),
            claimed_entry_edge=kw.get("claimed"),
        )

    def test_live_btc_case_no_edge_entry_bid_at_fair_allowed(self):
        """entry 78, fair 74, bid 74, edge -4 -> floor=min(78,74-2)=72 -> 74 OK."""
        c = self._cand()
        blocked = loss_sell_blocked(
            c.trigger_reason, c.executable_exit_cents, c.entry_price_cents,
            hold_value_cents=c.fair_value_cents,
            peak_price_cents=c.peak_price_cents,
            entry_edge=_candidate_floor_entry_edge(c),
        )
        self.assertFalse(blocked)

    def test_unwired_call_still_suppresses(self):
        """Documents the pre-fix behaviour: without edge inputs the floor is
        pinned to entry and every below-entry exit is suppressed."""
        c = self._cand()
        blocked = loss_sell_blocked(
            c.trigger_reason, c.executable_exit_cents, c.entry_price_cents,
            hold_value_cents=c.fair_value_cents,
        )
        self.assertTrue(blocked)

    def test_bid_below_probe_floor_still_suppressed(self):
        """bid < fair-2 (model says market underprices the position) -> hold."""
        c = self._cand(bid=70, fair=74)
        blocked = loss_sell_blocked(
            c.trigger_reason, 70, c.entry_price_cents,
            hold_value_cents=74,
            peak_price_cents=None,
            entry_edge=_candidate_floor_entry_edge(c),
        )
        self.assertTrue(blocked)

    def test_stamped_claim_edge_preferred_over_model_delta(self):
        c = self._cand(edge=+7, claimed=-5.0)
        self.assertEqual(_candidate_floor_entry_edge(c), -5.0)
        c2 = self._cand(edge=-4, claimed=None)
        self.assertEqual(_candidate_floor_entry_edge(c2), -4)

    def test_peak_ratchet_raises_floor_on_winner_roundtrip(self):
        """No-edge=None (positive-edge entry) + peak 86 (arm 8) -> floor=78."""
        c = self._cand(edge=+9, peak=86)
        blocked = loss_sell_blocked(
            c.trigger_reason, 74, c.entry_price_cents,
            hold_value_cents=74,
            peak_price_cents=c.peak_price_cents,
            entry_edge=_candidate_floor_entry_edge(c),
        )
        self.assertTrue(blocked)

    def test_loss_cap_exempt_regardless(self):
        c = self._cand(trigger="LOSS_CAP", bid=40)
        blocked = loss_sell_blocked(
            "LOSS_CAP", 40, 78, hold_value_cents=60,
            peak_price_cents=None, entry_edge=None,
        )
        self.assertFalse(blocked)


class TestLossCapSweep(unittest.TestCase):
    def test_loss_cap_sweeps_deeper(self):
        self.assertGreaterEqual(
            _stop_sweep_cents("LOSS_CAP"), 6,
        )

    def test_other_triggers_keep_default(self):
        from merid.event_venues.kalshi.stop_candidate import STOP_MAX_SLIPPAGE_CENTS
        self.assertEqual(_stop_sweep_cents("EDGE_DECAY"), STOP_MAX_SLIPPAGE_CENTS)
        self.assertEqual(_stop_sweep_cents("HARD_STOP"), STOP_MAX_SLIPPAGE_CENTS)

    def test_sweep_env_override(self):
        with mock.patch.dict(os.environ, {"MERID_LOSS_CAP_SWEEP_CENTS": "10"}):
            self.assertEqual(_stop_sweep_cents("LOSS_CAP"), 10)


class TestTailFloorRetry(unittest.TestCase):
    def setUp(self):
        self.cfg = _get_tail_loss_floor_config()
        self.cfg = dict(self.cfg, retry_s=20, max_attempts=4)

    def test_first_fire_allowed(self):
        self.assertTrue(_tail_floor_fire_allowed(_Pos(fired=False), self.cfg, 1000.0))

    def test_immediate_retry_blocked_by_cooldown(self):
        p = _Pos(fired=True, fired_at=1000.0, attempts=1)
        self.assertFalse(_tail_floor_fire_allowed(p, self.cfg, 1010.0))

    def test_retry_after_cooldown(self):
        p = _Pos(fired=True, fired_at=1000.0, attempts=1)
        self.assertTrue(_tail_floor_fire_allowed(p, self.cfg, 1020.0))

    def test_attempt_cap(self):
        p = _Pos(fired=True, fired_at=1000.0, attempts=4)
        self.assertFalse(_tail_floor_fire_allowed(p, self.cfg, 2000.0))

    def test_config_knobs_present(self):
        cfg = _get_tail_loss_floor_config()
        self.assertIn("retry_s", cfg)
        self.assertIn("max_attempts", cfg)


class TestCreateOrderParseAnnotation(unittest.TestCase):
    """The create-order response lacks action/book_side; annotating the
    request's direction must produce the correct PlacedOrder.side/outcome."""

    def _parse(self, resp, book_side, action):
        from merid.event_venues.kalshi.client import KalshiVenueClient
        client = KalshiVenueClient.__new__(KalshiVenueClient)
        data = dict(resp)
        data.setdefault("book_side", book_side)
        data.setdefault("action", action)
        return client._to_placed_order(data)

    def _resp(self):
        return {
            "order_id": "abc-123",
            "ticker": "KXBTC15M-T",
            "status": "executed",
            "fill_count_fp": "1.00",
            "remaining_count_fp": "0.00",
            "yes_price_dollars": "0.44",
            "no_price_dollars": "0.56",
        }

    def test_sell_via_bid_maps_to_no(self):
        # SELL_NO -> book_side=bid, action=sell -> held outcome no, side sell.
        o = self._parse(self._resp(), "bid", "sell")
        self.assertIsNotNone(o)
        self.assertEqual(o.side, "sell")
        self.assertEqual(o.outcome_id, "no")

    def test_buy_via_ask_maps_to_no(self):
        o = self._parse(self._resp(), "ask", "buy")
        self.assertEqual(o.side, "buy")
        self.assertEqual(o.outcome_id, "no")

    def test_buy_via_bid_maps_to_yes(self):
        o = self._parse(self._resp(), "bid", "buy")
        self.assertEqual(o.side, "buy")
        self.assertEqual(o.outcome_id, "yes")

    def test_sell_via_ask_maps_to_yes(self):
        # SELL_YES -> book_side=ask, action=sell -> held outcome yes, side sell.
        o = self._parse(self._resp(), "ask", "sell")
        self.assertEqual(o.side, "sell")
        self.assertEqual(o.outcome_id, "yes")


if __name__ == "__main__":
    unittest.main()
