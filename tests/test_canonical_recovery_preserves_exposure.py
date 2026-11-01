"""Canonical reconciliation must not erase exposure to manufacture agreement."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from merid.event_venues.kalshi.canonical_portfolio_reconciler import (
    CanonicalPortfolioReconciler,
)


def _snapshot(authoritative=False, version=1):
    return SimpleNamespace(
        is_authoritative=authoritative,
        pagination_complete=True,
        reconciliation_reason="position_mismatch",
        working_orders_by_id={},
        mismatches=("KXBTC15M-TEST:quantity_mismatch",),
        version=version,
    )


@pytest.mark.asyncio
async def test_recovery_retries_without_mutating_reservations_or_cache(monkeypatch):
    reconciler = object.__new__(CanonicalPortfolioReconciler)
    reconciler._mismatch_reconcile_attempt = 0
    reconciler._terminalize_impossible_local_intents = Mock()
    reconciler._rebuild_affected_cache_and_reservations = AsyncMock()
    reconciler.build_snapshot = AsyncMock(return_value=_snapshot(version=2))
    monkeypatch.setattr("merid.event_venues.kalshi.canonical_portfolio_reconciler.asyncio.sleep", AsyncMock())

    initial = _snapshot()
    result = await reconciler._recover_authority(initial)
    assert result is initial
    assert reconciler._recovery_state == "QUARANTINED"
    assert reconciler.build_snapshot.await_count == 3
    reconciler._terminalize_impossible_local_intents.assert_not_called()
    reconciler._rebuild_affected_cache_and_reservations.assert_not_awaited()


@pytest.mark.asyncio
async def test_mismatch_is_published_before_recovery_finishes():
    reconciler = object.__new__(CanonicalPortfolioReconciler)
    reconciler._running = False
    reconciler._task = None
    reconciler._build_in_progress = False
    reconciler._store = Mock()
    initial = _snapshot()
    reconciler.build_snapshot = AsyncMock(return_value=initial)
    entered = asyncio.Event()
    wait = asyncio.Event()

    async def recovery(snapshot):
        entered.set()
        await wait.wait()
        return snapshot

    reconciler._recover_authority = recovery
    await reconciler.start(interval=60)
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        reconciler._store.publish.assert_called_once_with(initial)
    finally:
        await reconciler.stop()
