"""Regression tests for REST position-snapshot dispositions (2026-11-01 audit).

The failing comparator treated an older/duplicate request losing the ordering
race as a portfolio-authority failure ("snapshot is not newer than the last
sync").  The repair separates "did not apply" (SUPERSEDED/CONFIRMED) from
"could not reconcile" (FAILED — raises).  Entry gating must stay fail-closed
only for genuinely unresolved state.
"""
import asyncio

import pytest

from merid.event_venues.kalshi.position_cache import (
    KalshiPositionCache,
    RestSnapshotDisposition,
)


def _fresh_cache(monkeypatch, current):
    """Minimal cache instance with a stubbed position projection."""
    import merid.preflight.p0 as p0

    cache = KalshiPositionCache.__new__(KalshiPositionCache)
    cache._positions = {}
    cache._last_sync = None
    cache._last_rest_sync_timestamp = 0.0
    cache._mutex = None

    state = {"current": dict(current)}
    monkeypatch.setattr(
        p0, "_signed_yes_position_map", lambda positions, exchange=False: dict(state["current"])
    )
    monkeypatch.setattr(
        p0,
        "_position_mismatches",
        lambda expected, actual, tag: (
            [] if expected == actual else [{"exp": expected, "act": actual, "tag": tag}]
        ),
    )
    monkeypatch.setattr(p0, "_reconciliation_quarantined", lambda ticker: False)
    return cache


@pytest.mark.asyncio
async def test_newer_snapshot_applies():
    cache = _fresh_cache(monkeypatch := pytest.MonkeyPatch(), {"T1": 100})
    disp = await cache.confirm_matched_rest_projection({"T1": 100}, 1000.0)
    assert disp == RestSnapshotDisposition.APPLIED
    assert cache._last_rest_sync_timestamp == 1000.0


@pytest.mark.asyncio
async def test_equal_version_equal_state_is_confirmed():
    cache = _fresh_cache(pytest.MonkeyPatch(), {"T1": 100})
    cache._last_rest_sync_timestamp = 1000.0
    disp = await cache.confirm_matched_rest_projection({"T1": 100}, 1000.0)
    assert disp == RestSnapshotDisposition.CONFIRMED_UNCHANGED


@pytest.mark.asyncio
async def test_older_refresh_after_newer_is_superseded_not_failed():
    """The audit's actual failure: request started before a newer sync applied."""
    cache = _fresh_cache(pytest.MonkeyPatch(), {"T1": 100})
    cache._last_rest_sync_timestamp = 2000.0  # newer observation already applied
    disp = await cache.confirm_matched_rest_projection({"T1": 100}, 1500.0)
    assert disp == RestSnapshotDisposition.SUPERSEDED_BY_NEWER_REFRESH
    # Watermark must not regress.
    assert cache._last_rest_sync_timestamp == 2000.0


@pytest.mark.asyncio
async def test_equal_version_different_state_fails_closed():
    cache = _fresh_cache(pytest.MonkeyPatch(), {"T1": 100})
    cache._last_rest_sync_timestamp = 1000.0
    with pytest.raises(RuntimeError, match="position cache changed"):
        await cache.confirm_matched_rest_projection({"T1": 999}, 1000.0)


@pytest.mark.asyncio
async def test_older_version_different_state_fails_closed():
    cache = _fresh_cache(pytest.MonkeyPatch(), {"T1": 100})
    cache._last_rest_sync_timestamp = 2000.0
    with pytest.raises(RuntimeError):
        await cache.confirm_matched_rest_projection({"T1": 999}, 1500.0)
