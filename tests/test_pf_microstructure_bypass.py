"""Regression: pinned_fav (bounded lane, stamped negative floor) must not be
killed by the edge-aware microstructure gate's positive executable-edge bound.

Live 2026-10-21 06:56: ETH buy_no@90c lane=pinned_fav ev=-0.94c was rejected
`signal_validation:microstructure_gate_failed:executable_edge_too_low:
raw_edge=1` after passing slot allocation — the gate applied the profile's
+3c bound to a lane admitted on authoritative executable economics at a -12c
floor.  The floor is enforced downstream by the edge-preserving repricer and
submit-time EV revalidation; the positive-edge gate is bypassed for bounded
lanes carrying a stamped floor.
"""

from unittest.mock import Mock, patch

import pytest


def _pf_intent():
    from merid.event_venues.kalshi.order_router import OrderIntent

    intent = OrderIntent(
        ticker="KXETH15M-26OCT210300-00",
        side="no",
        action="buy",
        price_cents=90,
        count=3,
        edge_pct=1.0,
        rationale="pinned_fav maker_bid admission: challenge_eligible",
        model_prob=0.91,
        p_hat_yes_cents=9.0,
        p_hat_no_cents=91.0,
        yes_bid_cents=9,
        yes_ask_cents=10,
        no_bid_cents=90,
        no_ask_cents=91,
        source="merid.prediction.agent_grid_15m",
        decision_lane="pinned_fav",
        min_required_edge=-0.12,
        ev_net_cents=-0.94,
    )
    return intent


def _generic_intent():
    intent = _pf_intent()
    intent.decision_lane = None
    intent.min_required_edge = None
    return intent


def _profile_mock():
    profile = Mock()
    profile.fee_aware_edge_enabled = False
    profile.market_microstructure_enabled = True
    profile.use_edge_aware_microstructure_gate = True
    profile.market_microstructure_max_spread_cents = 20
    profile.market_microstructure_min_yes_depth = 1
    profile.market_microstructure_min_no_depth = 1
    profile.momentum_fvg_liquidity_min_threshold = 1
    profile.strategy_policy_min_edge = 0.05
    profile.min_executable_edge_cents = 3.0
    profile.enable_liquidity_sanity_checks = False
    return profile


@pytest.fixture
def patched_gate():
    """Force the edge-aware gate to return its positive-edge rejection and
    stub the profile so earlier metadata gates pass."""
    with patch(
        "merid.risk.profiles.crypto_15m_profile.Crypto15mProfileAdapter"
    ) as mock_adapter, patch(
        "merid.event_venues.kalshi.order_router.check_market_microstructure_edge_aware"
    ) as mock_gate:
        mock_adapter.return_value.profile = _profile_mock()
        mock_gate.return_value = (
            False,
            "executable_edge_too_low: raw_edge=1.00c spread_cost=0.00c "
            "taker_fee=0.00c executable_edge=1.00c < min_executable_edge=3.00c",
        )
        yield mock_gate


def test_pinned_fav_bounded_lane_bypasses_positive_edge_gate(patched_gate):
    """A stamped pinned_fav intent survives a positive-edge gate failure —
    its lane floor is enforced downstream."""
    from merid.event_venues.kalshi.order_router import _validate_signal_metadata

    error = _validate_signal_metadata(_pf_intent())
    assert error is None or not str(error).startswith(
        "microstructure_gate_failed:executable_edge_too_low"
    ), f"pf bounded-lane intent must bypass the positive-edge gate, got: {error}"


def test_generic_lane_keeps_positive_edge_gate(patched_gate):
    """Unstamped/non-lane intents keep the positive executable-edge bound."""
    from merid.event_venues.kalshi.order_router import _validate_signal_metadata

    error = _validate_signal_metadata(_generic_intent())
    assert error is not None and str(error).startswith(
        "microstructure_gate_failed:"
    ), f"generic intent should still be rejected by the edge gate, got: {error}"


def test_window_quota_bypass_preserved(patched_gate):
    """The original quota bypass still fires unconditionally on the lane."""
    from merid.event_venues.kalshi.order_router import _validate_signal_metadata

    intent = _pf_intent()
    intent.decision_lane = "window_quota"
    intent.min_required_edge = None
    error = _validate_signal_metadata(intent)
    assert error is None or not str(error).startswith(
        "microstructure_gate_failed:executable_edge_too_low"
    ), f"window_quota bypass must be preserved, got: {error}"
