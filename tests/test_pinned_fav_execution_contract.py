"""Regression: pinned_fav is an immutable maker lane end-to-end.

Live 2026-10-29: an ETH-YES pinned_fav post-only bid at the 92c MAKER_LO
floor was rejected ``post only cross``, then the maker->taker conversion
submitted an IOC that swept the repriced book and filled 4@91.5 + 2@91.6 —
*below* the 92c floor the lane exists to defend — and settled NO for -552c.

The lane contract is now unconditional: ``resolve_bounded_lane_execution_policy``
returns a maker ExecutionPolicy with ``allow_taker_fallback=False`` for every
pinned_fav intent, the IOC-conversion path honors that flag for entries, and
the strict-passivity repricer may not drift below the lane's admission band.
"""

import ast


def _intent(**kw):
    from merid.event_venues.kalshi.order_router import OrderIntent

    base = dict(
        ticker="KXETH15M-26OCT291215-15",
        side="yes",
        action="buy",
        price_cents=92,
        count=2.0,
        post_only=True,
        decision_lane="pinned_fav",
    )
    base.update(kw)
    return OrderIntent(**base)


def test_pinned_fav_policy_is_immutable_maker():
    from merid.event_venues.kalshi.order_router import (
        resolve_bounded_lane_execution_policy,
    )

    pol = resolve_bounded_lane_execution_policy("pinned_fav", post_only=True)
    assert pol is not None
    assert pol.lane == "pinned_fav"
    assert pol.required_post_only is True
    assert pol.required_liquidity_role == "maker"
    assert pol.allow_taker_fallback is False


def test_pinned_fav_taker_posture_still_gets_maker_contract():
    """A non-post-only pinned_fav intent carries the maker contract too, so
    it fails closed at PRE_WIRE_POST_ONLY_UNAVAILABLE instead of routing
    taker.  The lane is maker-mode by design."""
    from merid.event_venues.kalshi.order_router import (
        resolve_bounded_lane_execution_policy,
        _intent_requires_post_only,
    )

    pol = resolve_bounded_lane_execution_policy("pinned_fav", post_only=False)
    assert pol is not None
    assert pol.required_post_only is True
    assert pol.allow_taker_fallback is False

    intent = _intent(post_only=False)
    intent.execution_policy = pol
    assert _intent_requires_post_only(intent) is True


def test_intent_requires_post_only_via_stamped_policy():
    from merid.event_venues.kalshi.order_router import (
        resolve_bounded_lane_execution_policy,
        _intent_requires_post_only,
    )

    intent = _intent()
    intent.execution_policy = resolve_bounded_lane_execution_policy(
        "pinned_fav", True)
    assert _intent_requires_post_only(intent) is True


def test_strict_passivity_reprice_cannot_drift_below_lane_band(monkeypatch):
    """The current 94c floor must not be repriced to 93c."""
    from merid.event_venues.kalshi.order_router import (
        _post_only_strict_passivity,
    )

    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MODE", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_LO", "94")
    intent = _intent(price_cents=94)
    new_px, reason = _post_only_strict_passivity(
        intent, {"bid_cents": 92, "ask_cents": 94}
    )
    assert new_px is None
    assert reason is not None
    assert "below_lane_band" in reason


def test_strict_passivity_in_band_reprice_still_allowed(monkeypatch):
    from merid.event_venues.kalshi.order_router import (
        _post_only_strict_passivity,
    )

    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MODE", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_LO", "94")
    intent = _intent(price_cents=96)
    new_px, reason = _post_only_strict_passivity(
        intent, {"bid_cents": 94, "ask_cents": 96}
    )
    assert new_px == 95
    assert reason is None


def test_strict_passivity_unlaned_intent_unchanged():
    """Ordinary (unlaned) intents keep the pre-existing behavior — the lane
    floor only binds bounded admission lanes."""
    from merid.event_venues.kalshi.order_router import (
        _post_only_strict_passivity,
    )

    intent = _intent(decision_lane=None, price_cents=92)
    new_px, reason = _post_only_strict_passivity(
        intent, {"bid_cents": 90, "ask_cents": 92}
    )
    assert new_px == 91
    assert reason is None


def test_ioc_conversion_honors_allow_taker_fallback():
    """AST pin: the maker->taker conversion in route_order_async must gate
    entries on execution_policy.allow_taker_fallback so a maker lane can
    never be downgraded to taker on post-only-cross."""
    import inspect
    from merid.event_venues.kalshi import order_router
    src = inspect.getsource(order_router)
    tree = ast.parse(src)
    conv = None

    def _walk(node):
        nonlocal conv
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.AsyncFunctionDef) and \
                    child.name == "_convert_to_ioc":
                conv = child
            _walk(child)

    _walk(tree)
    assert conv is not None, "_convert_to_ioc not found in order_router.py"
    body = ast.dump(conv)
    assert "allow_taker_fallback" in body, (
        "_convert_to_ioc does not consult execution_policy."
        "allow_taker_fallback — maker lanes can still be swept taker"
    )
    assert "pinned_fav" in body, (
        "_convert_to_ioc lost the unstamped-lane fallback — a pinned_fav "
        "intent without execution_policy must still be vetoed"
    )


def test_dead_market_suppresses_exit_proposals():
    """_market_is_terminal_id must classify a past-window ticker terminal so
    the arbiter stops minting never_transmitted exit attempts on settled
    markets (live: ~46 attempts in ~80s on KXBTC15M-26OCT291230-30)."""
    from merid.position_management.exit_arbiter import _market_is_terminal_id
    from merid.event_venues.kalshi.expiry_fallback import (
        parse_kalshi_15m_window_end_utc,
    )
    import pytest

    if parse_kalshi_15m_window_end_utc("KXBTC15M-26OCT291230-30") is None:
        pytest.skip("ticker parse unavailable in this environment")
    assert _market_is_terminal_id("KXBTC15M-26OCT291230-30") is True
    assert _market_is_terminal_id("not-a-ticker") is False
