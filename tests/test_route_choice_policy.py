"""Regression tests for the price-aware maker/taker route selection.

2026-10-08: the routing audit found taker-qualified candidates were being
forced into the post-only lane whenever their gross edge fell below
``MERID_TAKER_EDGE_THRESHOLD`` — 5 of 6 such resting orders failed to fill
in a 24h window (incl. a venue ``post only cross`` on XRP).  The replacement
policy compares *certain* taker surplus against *fill-probability-adjusted*
maker edge via ``_route_prefers_taker``.

These tests pin the contract:

  * taker wins whenever its net EV >= p_fill * maker net EV + margin;
  * maker wins only when its fill-adjusted edge genuinely dominates;
  * a default 0.20 fill-probability estimate is conservative (measured
    resting-entry fill rate ~15-25% before rollover/cancel);
  * maker fill probability is clamped to [0, 1] so a misconfigured env var
    cannot flip the ordering;
  * a positive taker-preference margin shifts the crossover upward.
"""

import unittest


class TestRoutePrefersTaker(unittest.TestCase):
    """Unit coverage for ``_route_prefers_taker`` pure comparison."""

    def _fn(self):
        from merid.prediction.agent_grid_15m import _route_prefers_taker
        return _route_prefers_taker

    def test_taker_wins_when_surplus_beats_fill_adjusted_maker(self):
        """XRP case: taker +0.78c vs maker +2.29c at p_fill=0.20.

        0.78 >= 0.20 * 2.29 + 0  =>  True (IOC is the correct route — the
        resting order never filled, venue rejected it 'post only cross').
        """
        self.assertTrue(self._fn()(0.78, 2.29, 0.20))

    def test_maker_wins_when_fill_adjusted_edge_dominates(self):
        """Large passive edge: taker +0.10c vs maker +8.0c at p_fill=0.20.

        0.10 < 1.6  =>  False (resting order is worth more expected value).
        """
        self.assertFalse(self._fn()(0.10, 8.00, 0.20))

    def test_equal_economics_prefers_taker_certainty(self):
        """At the exact crossover the certain fill wins (>=, not >)."""
        # 1.0 * 0.20 = 0.20 == taker 0.20 -> taker
        self.assertTrue(self._fn()(0.20, 1.00, 0.20))

    def test_fill_prob_clamped_above_one(self):
        """Misconfigured p_fill=1.5 must not invert the ordering."""
        # clamped to 1.0: taker 2.0 vs maker 1.5 -> taker wins.
        self.assertTrue(self._fn()(2.0, 1.5, 1.5))

    def test_fill_prob_clamped_below_zero(self):
        """Negative p_fill degenerates to 'taker iff taker net >= margin'."""
        self.assertTrue(self._fn()(0.0, 9.9, -0.5))
        self.assertFalse(self._fn()(-0.01, 9.9, -0.5))

    def test_pref_margin_shifts_crossover(self):
        """A +0.5c taker-preference margin lowers the taker hurdle."""
        # Without margin: 0.40 < 0.20*2.29=0.458 -> maker.
        self.assertFalse(self._fn()(0.40, 2.29, 0.20))
        # With margin -0.5c (taker preference): maker hurdle drops.
        # use_taker = t_net >= p_fill*m_net + margin
        self.assertTrue(self._fn()(0.40, 2.29, 0.20, -0.5))

    def test_zero_maker_edge_always_taker(self):
        """maker_net=0 (qualified but worthless passive EV) -> taker."""
        self.assertTrue(self._fn()(0.01, 0.0, 0.20))


class TestMakerToTakerConversion(unittest.TestCase):
    """Source-level regression guards for the bounded maker->taker IOC
    conversion added 2026-10-08.

    Observed live (KXXRP15M-26OCT081830-30): post-only YES bid @67c rested
    ~4.3s, venue rejected 'post only cross', passive reprice to @60c was
    *also* cross-rejected -> terminal reject.  The conversion lets an
    economically-qualified candidate take the moved ask as IOC instead.
    """

    def _src(self):
        import inspect
        import merid.event_venues.kalshi.order_router as _or
        return inspect.getsource(_or)

    def test_conversion_helper_exists_and_is_one_shot(self):
        src = self._src()
        assert "_convert_to_ioc" in src
        # Bounded to exactly one conversion per intent.
        assert "_postonly_converted_taker" in src

    def test_conversion_is_ioc_not_post_only(self):
        src = self._src()
        conv_pos = src.find("async def _convert_to_ioc")
        assert conv_pos > 0
        seg = src[conv_pos:conv_pos + 6000]
        assert 'effective_tif="ioc"' in seg
        assert "post_only=False" in seg

    def test_conversion_qualified_by_edge_preserving_cap(self):
        """Fresh taker qualification = fresh ask <= _max_edge_preserving_buy_price;
        the IOC limit is min(ask, cap) — never chase beyond the economic bound."""
        src = self._src()
        conv_pos = src.find("async def _convert_to_ioc")
        seg = src[conv_pos:conv_pos + 6000]
        assert "_max_edge_preserving_buy_price(intent)" in seg
        assert "_cb_ask <= 0 or _cb_ask > _cap" in seg
        assert "min(_cb_ask, _cap)" in seg

    def test_conversion_mints_fresh_wire_coid(self):
        """The rejected maker submission consumed the coid venue-side — the
        conversion must mint a fresh wire id ('t1') mirroring the 'r1'
        reprice convention, else Kalshi 409-duplicates it."""
        src = self._src()
        assert 'f"{intent.client_order_id}t1"' in src
        assert "maker_to_taker_conversion" in src
        assert "conversion_of_client_order_id" in src

    def test_conversion_runs_after_repriced_cross_reject(self):
        """Site 2: a passive reprice that is *itself* cross-rejected must
        reach the conversion path (the XRP live case)."""
        src = self._src()
        retry_pos = src.find('"reprice_of_client_order_id"')
        assert retry_pos > 0
        after = src[retry_pos:retry_pos + 9000]
        # Within the reprice-retry region, a second 'post only cross' result
        # must invoke _convert_to_ioc.
        assert '"post only cross"' in after and "_convert_to_ioc()" in after

    def test_conversion_is_buy_only_and_not_exit(self):
        src = self._src()
        conv_pos = src.find("async def _convert_to_ioc")
        seg = src[conv_pos:conv_pos + 3000]
        assert '"buy"' in seg  # action guard — entries are always buys here
        # Outer post-only-cross block is already gated on not _is_exit_order.
        outer = src.find('"post only cross" in _po_err_lower')
        guard = src.rfind("not _is_exit_order(intent)", 0, outer + 500)
        assert guard > 0


class TestRouteSelectionIntegration(unittest.TestCase):
    """Pin the routing contract around the selection block:

    taker-qualified + maker-failed => IOC (post_only=False, tif=ioc).
    """

    def test_source_routes_taker_when_maker_pass_fails(self):
        """Static check: the 'not _maker_sel' shortcut sends IOC."""
        import inspect
        from merid.prediction import agent_grid_15m as ag

        src = inspect.getsource(ag)
        # The precomputed maker pass must exist before route selection so
        # 'forced passive' can never be decided without maker economics.
        self.assertIn("decision_maker = _call_trade_decision(", src)
        # Taker-qualified + no qualified passive alternative -> IOC.
        self.assertIn("or not _maker_sel", src)
        # The IOC contract flags are still set in the taker branch.
        self.assertIn('time_in_force = "ioc"', src)
        self.assertIn("post_only = False", src)


if __name__ == "__main__":
    unittest.main()
