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
