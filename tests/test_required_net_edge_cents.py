"""Unit tests for required_net_edge_cents — the allocator EDGE-stage hurdle SSOT.

The function returns the required net edge in cents.  The default path must
reproduce the pre-refactor inline computation (generic floor vs lane bound,
plus the degraded reserve on either base) so every non-settlement lane is
behaviour-identical.
"""

import pytest

from merid.risk.profiles.global_allocator import required_net_edge_cents


def _frac(cents: float) -> float:
    return cents / 100.0


class TestDefaultPath:
    def test_generic_floor_no_degraded(self):
        # 2.5% floor -> 2.5 cents-equivalent, no reserve.
        assert required_net_edge_cents(
            asset_min_edge_frac=0.025, degraded=False,
            degraded_reserve_frac=0.01, lane_bound_cents=None, is_lane=False,
        ) == pytest.approx(2.5)

    def test_generic_floor_degraded_adds_reserve(self):
        # 2.5% floor + 1% degraded reserve -> 3.5 cents-equivalent.
        assert required_net_edge_cents(
            asset_min_edge_frac=0.025, degraded=True,
            degraded_reserve_frac=0.01, lane_bound_cents=None, is_lane=False,
        ) == pytest.approx(3.5)

    def test_degraded_false_ignores_reserve_frac(self):
        assert required_net_edge_cents(
            asset_min_edge_frac=0.025, degraded=False,
            degraded_reserve_frac=0.05, lane_bound_cents=None, is_lane=False,
        ) == pytest.approx(2.5)

    def test_lane_bound_replaces_generic_floor(self):
        # Lane bound (cents) + degraded reserve; generic floor not added.
        assert required_net_edge_cents(
            asset_min_edge_frac=0.025, degraded=False,
            degraded_reserve_frac=0.01, lane_bound_cents=0.75, is_lane=True,
        ) == pytest.approx(0.75)

    def test_lane_bound_degraded(self):
        assert required_net_edge_cents(
            asset_min_edge_frac=0.025, degraded=True,
            degraded_reserve_frac=0.01, lane_bound_cents=0.75, is_lane=True,
        ) == pytest.approx(1.75)

    def test_lane_bound_negative_value_lane(self):
        # Value lanes may carry a negative bound; reserve still applies on top.
        assert required_net_edge_cents(
            asset_min_edge_frac=0.025, degraded=True,
            degraded_reserve_frac=0.01, lane_bound_cents=-3.0, is_lane=True,
        ) == pytest.approx(-2.0)

    def test_lane_bound_ignored_when_not_lane(self):
        # A stamped bound on a non-lane candidate must not leak through.
        assert required_net_edge_cents(
            asset_min_edge_frac=0.025, degraded=False,
            degraded_reserve_frac=0.01, lane_bound_cents=0.75, is_lane=False,
        ) == pytest.approx(2.5)

    def test_lane_without_bound_falls_back_to_generic(self):
        assert required_net_edge_cents(
            asset_min_edge_frac=0.03, degraded=True,
            degraded_reserve_frac=0.005, lane_bound_cents=None, is_lane=True,
        ) == pytest.approx(3.5)


class TestLegacyEquivalence:
    """The default path must equal the pre-refactor fraction-space formula."""

    @staticmethod
    def _legacy(amef, degraded, lbc, is_lane, dfr=0.01):
        d = dfr if degraded else 0.0
        if is_lane and lbc is not None:
            return float(lbc) / 100.0 + d
        return amef + d

    @pytest.mark.parametrize("amef", [0.0, 0.005, 0.01, 0.025, 0.03, 0.05, -0.02])
    @pytest.mark.parametrize("degraded", [False, True])
    @pytest.mark.parametrize("lbc", [None, -15.0, -3.0, -0.5, 0.0, 0.75, 1.0, 2.5])
    @pytest.mark.parametrize("is_lane", [False, True])
    def test_fraction_equivalence(self, amef, degraded, lbc, is_lane):
        new_frac = required_net_edge_cents(
            asset_min_edge_frac=amef, degraded=degraded,
            degraded_reserve_frac=0.01, lane_bound_cents=lbc, is_lane=is_lane,
        ) / 100.0
        assert new_frac == pytest.approx(self._legacy(amef, degraded, lbc, is_lane))
