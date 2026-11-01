"""Fill-during-fetch and complete-empty-portfolio reconciliation (2026-11-01).

Covers the two remaining reconciliation-race cases:
  1. A fill that changes local state while a REST positions request is in
     flight: the older response must not overwrite newer state, entries stay
     blocked (FAILED raises into the caller's halt path), a bounded re-fetch
     reconciles, and a persistent unexplained difference never ages into
     acceptance.
  2. A complete, correctly-scoped empty response establishes zero positions —
     distinct from a failed request, a truncated page, a wrong account, or an
     intervening fill, all of which fail closed rather than zero live state.
"""
import pytest

import merid.preflight.p0 as p0
from merid.event_venues.kalshi.position_cache import (
    KalshiPositionCache,
    RestSnapshotDisposition,
)


def _cache(monkeypatch, current):
    """Cache whose projected signed-YES map is externally mutable — mutating
    ``state['current']`` simulates a fill applying local state mid-flight."""
    cache = KalshiPositionCache.__new__(KalshiPositionCache)
    cache._positions = {}
    cache._last_sync = None
    cache._last_rest_sync_timestamp = 0.0
    cache._mutex = None
    state = {"current": dict(current)}
    monkeypatch.setattr(
        p0, "_signed_yes_position_map",
        lambda positions, exchange=False: dict(state["current"]),
    )
    monkeypatch.setattr(
        p0, "_position_mismatches",
        lambda expected, actual, tag: (
            [] if expected == actual else [{"exp": expected, "act": actual, "tag": tag}]
        ),
    )
    monkeypatch.setattr(p0, "_reconciliation_quarantined", lambda ticker: False)
    return cache, state


@pytest.mark.asyncio
async def test_fill_during_fetch_older_response_cannot_overwrite(monkeypatch):
    cache, state = _cache(monkeypatch, {"T1": 500})

    # REST request started (rest_timestamp=1000) observing {T1:500}.
    # While the response is in flight a fill changes local state:
    state["current"]["T2"] = 300

    # The older response arrives: content diverged during flight -> FAILED
    # (raises into the caller's halt path; entries stay blocked).
    with pytest.raises(RuntimeError):
        await cache.confirm_matched_rest_projection(
            {"T1": 500}, 1000.0, caller="test")

    # Newer fill-derived state is preserved — the fetch wrote nothing.
    assert state["current"] == {"T1": 500, "T2": 300}
    assert cache._last_rest_sync_timestamp == 0.0

    # Bounded re-fetch (next poll cycle, fresh request timestamp) now sees
    # the fill in the exchange view and reconciles.
    disp = await cache.confirm_matched_rest_projection(
        {"T1": 500, "T2": 300}, 2000.0, caller="test")
    assert disp == RestSnapshotDisposition.APPLIED
    assert cache._last_rest_sync_timestamp == 2000.0


@pytest.mark.asyncio
async def test_persistent_unexplained_difference_never_ages_into_acceptance(
        monkeypatch):
    cache, state = _cache(monkeypatch, {"T1": 500, "T2": 300})

    # Every re-fetch that still disagrees fails closed — each poll is a fresh
    # request; divergence is never treated as acceptable by repetition.
    for ts in (1000.0, 2000.0, 3000.0):
        with pytest.raises(RuntimeError):
            await cache.confirm_matched_rest_projection(
                {"T1": 500}, ts, caller="test")
    assert cache._last_rest_sync_timestamp == 0.0


@pytest.mark.asyncio
async def test_complete_empty_portfolio_establishes_zero(monkeypatch):
    cache, _ = _cache(monkeypatch, {})

    # A complete, correctly-scoped empty response against an empty cache is a
    # valid observation: it establishes zero positions and advances the
    # watermark.
    disp = await cache.confirm_matched_rest_projection({}, 1000.0)
    assert disp == RestSnapshotDisposition.APPLIED
    assert cache._last_rest_sync_timestamp == 1000.0

    # Repeating the identical complete observation is a valid confirmation,
    # not an error (idempotent empty portfolio).
    disp = await cache.confirm_matched_rest_projection({}, 1000.0)
    assert disp == RestSnapshotDisposition.CONFIRMED_UNCHANGED


@pytest.mark.asyncio
async def test_empty_response_cannot_zero_a_live_position(monkeypatch):
    # Wrong account scope, an intervening fill, or a truncated page all look
    # alike at the content level: REST says empty while local state is not.
    # That must fail closed — it cannot silently establish zero.
    cache, state = _cache(monkeypatch, {"T1": 500})
    with pytest.raises(RuntimeError):
        await cache.confirm_matched_rest_projection({}, 1000.0)
    assert state["current"] == {"T1": 500}
    assert cache._last_rest_sync_timestamp == 0.0


def test_failed_or_truncated_fetch_rejected_before_cache_sync():
    """Completeness gate upstream of the cache: a failed/truncated/non-list
    fetch raises in _complete_snapshot and never reaches the cache.  An empty
    response that passed this gate is therefore a *complete* empty."""
    class _Failed:
        success = False
        error = "http500"
        metadata = {}

    class _Truncated:
        success = True
        error = None
        metadata = {"truncated": True}

    with pytest.raises(RuntimeError, match="incomplete"):
        p0._complete_snapshot(_Failed(), "positions")
    with pytest.raises(RuntimeError, match="incomplete"):
        p0._complete_snapshot(_Truncated(), "positions")
    with pytest.raises(RuntimeError, match="complete list"):
        p0._complete_snapshot({"not": "a list"}, "positions")
    # Complete empty list passes the gate — distinguishable from a failure.
    assert p0._complete_snapshot([], "positions") == []
