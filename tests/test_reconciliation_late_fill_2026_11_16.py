"""Regression tests for the 2026-11-16 XRP reconciliation incident.

Incident: a SELL exit fill propagated to the local stack 157s after the
exchange fill.  Three defects combined:

1. ``FillsPoller._do_poll`` queried Kalshi ``/portfolio/fills`` with
   ``min_ts = now - poll_interval*2`` (~20s).  Any fill propagating slower
   than the window permanently fell outside the query range — invisible to
   every poll until the 24h backfill caught it -> ``exchange=0`` vs
   ``ledger=+600`` -> global entry halt.

2. ``POSITION-CACHE-SYNC-CLOSE`` deleted the cached position + monitor while
   the exit fill was still in flight -> late fill hit
   ``EXIT FILL WITHOUT EXISTING POSITION``.

3. ``_reconciliation_halted`` only cleared via settlement because flat
   tickers absent from the REST positions payload were never re-evaluated ->
   ``PORTFOLIO_FAULT_LATCHED`` persisted ~6min after all three exposures
   reached 0.

4. ``EXIT-ORDER-PARTIAL`` re-armed a remaining close on an order that was
   already terminal on the exchange (``ORDER_NOT_TERMINAL`` stale status).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Fix 1: watermark-based fills poll lookback ────────────────────────────────


def _make_poller():
    from merid.event_venues.kalshi.fills_poller import FillsPoller

    p = FillsPoller.__new__(FillsPoller)
    p._fills_watermark_ms = None
    p._poll_interval = 10.0
    return p


def test_poll_lookback_without_watermark_uses_max_lookback(monkeypatch):
    monkeypatch.setenv("MERID_FILLS_POLL_MAX_LOOKBACK_S", "900")
    monkeypatch.setenv("MERID_FILLS_POLL_OVERLAP_S", "120")
    p = _make_poller()
    # No watermark and no circuit-breaker watermark -> bounded recent window.
    with patch(
        "merid.governance.trading_circuit_breaker.get_trading_circuit_breaker",
        side_effect=Exception("no breaker"),
    ):
        since_ms = p._poll_lookback_since_ts_ms()
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    assert now_ms - since_ms == pytest.approx(900_000, abs=5_000)


def test_poll_lookback_recent_fill_still_covered(monkeypatch):
    """A fill 60s old must remain inside the query window even though the
    old 20s wall-clock window would have excluded it."""
    monkeypatch.setenv("MERID_FILLS_POLL_MAX_LOOKBACK_S", "900")
    monkeypatch.setenv("MERID_FILLS_POLL_OVERLAP_S", "120")
    p = _make_poller()
    fill_ts = datetime.now(timezone.utc) - timedelta(seconds=60)
    p._fills_watermark_ms = int(fill_ts.timestamp() * 1000)
    since_ms = p._poll_lookback_since_ts_ms()
    # Window must reach back at least to the fill's created_time.
    assert since_ms <= int(fill_ts.timestamp() * 1000)


def test_poll_lookback_old_fill_clamped_to_max(monkeypatch):
    """An idle account must not rescan hours of history every poll."""
    monkeypatch.setenv("MERID_FILLS_POLL_MAX_LOOKBACK_S", "900")
    monkeypatch.setenv("MERID_FILLS_POLL_OVERLAP_S", "120")
    p = _make_poller()
    old_ts = datetime.now(timezone.utc) - timedelta(hours=3)
    p._fills_watermark_ms = int(old_ts.timestamp() * 1000)
    since_ms = p._poll_lookback_since_ts_ms()
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    assert now_ms - since_ms <= 900_000 + 5_000


def test_note_fills_watermark_advances_only_forward():
    p = _make_poller()
    t1 = datetime.now(timezone.utc) - timedelta(seconds=30)
    t2 = datetime.now(timezone.utc) - timedelta(seconds=10)
    p._note_fills_watermark(
        [MagicMock(created_time=t1), MagicMock(created_time=t2)]
    )
    assert p._fills_watermark_ms == int(t2.timestamp() * 1000)
    # Older observation must not regress the watermark.
    p._note_fills_watermark([MagicMock(created_time=t1)])
    assert p._fills_watermark_ms == int(t2.timestamp() * 1000)


def test_note_fills_watermark_handles_port_fill_timestamp_field():
    p = _make_poller()
    ts = datetime.now(timezone.utc)
    fill = MagicMock(spec=["timestamp"])
    fill.timestamp = ts
    fill.created_time = None
    p._note_fills_watermark([fill])
    assert p._fills_watermark_ms == int(ts.timestamp() * 1000)


# ── Fix 2: SYNC-CLOSE unresolved-exit guard ───────────────────────────────────


def _make_cache():
    from merid.event_venues.kalshi.position_cache import PositionCache

    c = PositionCache.__new__(PositionCache)
    c._positions = {}
    c._reconciliation_halted = {}
    c._applied_fill_ids = set()
    return c


def test_sync_close_defers_when_recent_unresolved_exit_attempt(monkeypatch):
    cache = _make_cache()
    market = "KXXRP15M-26NOV161400-00"
    monkeypatch.setenv("MERID_SYNC_CLOSE_EXIT_GRACE_S", "300")

    att = MagicMock()
    att.ticker = market
    att.created_at = datetime.now(timezone.utc).timestamp()

    with patch(
        "merid.event_venues.kalshi.order_attempt_store.OrderAttemptStore"
    ) as store_cls:
        store_cls.return_value.list_nonterminal_exit_attempts.return_value = [att]
        assert cache._has_recent_unresolved_exit_attempt(market) is True


def test_sync_close_does_not_defer_for_terminal_or_stale_attempt(monkeypatch):
    cache = _make_cache()
    market = "KXXRP15M-26NOV161400-00"
    monkeypatch.setenv("MERID_SYNC_CLOSE_EXIT_GRACE_S", "300")

    stale = MagicMock()
    stale.ticker = market
    stale.created_at = datetime.now(timezone.utc).timestamp() - 600

    other = MagicMock()
    other.ticker = "KXBTC15M-26NOV161400-00"
    other.created_at = datetime.now(timezone.utc).timestamp()

    with patch(
        "merid.event_venues.kalshi.order_attempt_store.OrderAttemptStore"
    ) as store_cls:
        store_cls.return_value.list_nonterminal_exit_attempts.return_value = [
            stale, other
        ]
        assert cache._has_recent_unresolved_exit_attempt(market) is False


def test_sync_close_attempt_store_failure_fails_open(monkeypatch):
    cache = _make_cache()
    market = "KXXRP15M-26NOV161400-00"
    with patch(
        "merid.event_venues.kalshi.order_attempt_store.OrderAttemptStore",
        side_effect=Exception("db locked"),
    ):
        assert cache._has_recent_unresolved_exit_attempt(market) is False


# ── Fix 4: venue terminal refresh before re-arm ───────────────────────────────


@pytest.mark.asyncio
async def test_venue_exit_order_terminal_detects_filled():
    from merid.loop_15m import _venue_exit_order_terminal

    result = MagicMock(order_id="ord-1")
    position = MagicMock(market_id="KXXRP15M-26NOV161400-00")
    intent = MagicMock(client_order_id="exit_abc")
    attempt = MagicMock(client_order_id=None)

    order = MagicMock(status="filled")
    client = MagicMock()
    client.get_order_result = AsyncMock(
        return_value=MagicMock(success=True, unwrap_or=lambda default=None: order)
    )
    with patch(
        "merid.event_venues.kalshi.client.get_kalshi_client",
        return_value=client,
    ):
        assert (
            await _venue_exit_order_terminal(result, position, intent, attempt)
            is True
        )


@pytest.mark.asyncio
async def test_venue_exit_order_terminal_detects_working():
    from merid.loop_15m import _venue_exit_order_terminal

    result = MagicMock(order_id=None)
    position = MagicMock(market_id="KXXRP15M-26NOV161400-00")
    intent = MagicMock(client_order_id="exit_abc")
    attempt = MagicMock(client_order_id=None)

    order = MagicMock(status="resting")
    client = MagicMock()
    client.get_order_by_client_id_result = AsyncMock(
        return_value=MagicMock(success=True, unwrap_or=lambda default=None: order)
    )
    with patch(
        "merid.event_venues.kalshi.client.get_kalshi_client",
        return_value=client,
    ):
        assert (
            await _venue_exit_order_terminal(result, position, intent, attempt)
            is False
        )


@pytest.mark.asyncio
async def test_venue_exit_order_terminal_unknown_on_lookup_failure():
    from merid.loop_15m import _venue_exit_order_terminal

    result = MagicMock(order_id="ord-1")
    position = MagicMock(market_id="KXXRP15M-26NOV161400-00")
    intent = MagicMock(client_order_id=None)
    attempt = MagicMock(client_order_id=None)

    client = MagicMock()
    client.get_order_result = AsyncMock(side_effect=Exception("404"))
    with patch(
        "merid.event_venues.kalshi.client.get_kalshi_client",
        return_value=client,
    ):
        assert (
            await _venue_exit_order_terminal(result, position, intent, attempt)
            is None
        )


@pytest.mark.asyncio
async def test_venue_exit_order_terminal_none_without_identifiers():
    from merid.loop_15m import _venue_exit_order_terminal

    result = MagicMock(order_id=None)
    position = MagicMock(market_id="KXXRP15M-26NOV161400-00")
    intent = MagicMock(client_order_id=None)
    attempt = MagicMock(client_order_id=None)
    assert (
        await _venue_exit_order_terminal(result, position, intent, attempt)
        is None
    )
