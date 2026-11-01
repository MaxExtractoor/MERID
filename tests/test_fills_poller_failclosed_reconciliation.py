"""Reconciliation must not erase state or report readiness on incomplete evidence."""

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from merid.event_venues.kalshi.fills_poller import FillsPoller
from merid.event_venues.kalshi.port import Position


@pytest.fixture
def harness(monkeypatch):
    poller = FillsPoller()
    client = SimpleNamespace(
        connect=AsyncMock(),
        get_positions=AsyncMock(return_value=SimpleNamespace(positions=[])),
    )
    view = SimpleNamespace(authoritative=[], provisional=[], excluded=[])
    ledger = SimpleNamespace(
        _load_complete=True,
        _last_load_error=None,
        get_canonical_fills=Mock(return_value=view),
        reconcile_with_kalshi_positions=AsyncMock(
            return_value={"status": "ok", "settled_tickers": []}
        ),
        clear_open_positions_on_empty_cache=AsyncMock(),
        compute_net_positions=Mock(return_value={}),
        maybe_record_eod_snapshot=Mock(),
    )
    cache = SimpleNamespace(
        get_all_positions=Mock(return_value={}),
        sync_from_rest=AsyncMock(),
        confirm_matched_rest_projection=AsyncMock(),
    )
    monkeypatch.setattr(poller, "_get_client", lambda: client)
    monkeypatch.setattr(poller, "_reconcile_submission_unknown_records", AsyncMock())
    monkeypatch.setattr(poller, "_sweep_expired_market_attempts", Mock())
    halt = Mock()
    monkeypatch.setattr(poller, "_halt_for_reconciliation", halt)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.fills_ledger.get_fills_ledger", lambda: ledger
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.position_cache.get_position_cache", lambda: cache
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.position_drift_detector.get_position_drift_detector",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr("merid.preflight.p0._reconciliation_quarantined", lambda ticker: False)
    return SimpleNamespace(poller=poller, client=client, ledger=ledger, cache=cache, halt=halt)


@pytest.mark.asyncio
async def test_malformed_position_stops_before_cache_sync(harness):
    harness.client.get_positions.return_value = SimpleNamespace(positions=[
        Position(ticker="", outcome="yes", size=Decimal("1"), average_entry_price_cents=50)
    ])
    report = await harness.poller._do_reconcile()
    assert report["status"] == "error"
    assert "malformed exchange position" in report["message"]
    harness.cache.sync_from_rest.assert_not_awaited()
    harness.cache.confirm_matched_rest_projection.assert_not_awaited()
    harness.halt.assert_called()


@pytest.mark.asyncio
async def test_ledger_position_disagreement_does_not_rewrite_cache(harness):
    harness.client.get_positions.return_value = SimpleNamespace(positions=[
        Position(ticker="BTC", outcome="yes", size=Decimal("1.23"), average_entry_price_cents=50)
    ])
    report = await harness.poller._do_reconcile()
    assert report["status"] == "error"
    assert "BTC:exchange=123:ledger=0" in report["message"]
    harness.cache.sync_from_rest.assert_not_awaited()
    harness.cache.confirm_matched_rest_projection.assert_not_awaited()
    harness.ledger.clear_open_positions_on_empty_cache.assert_not_awaited()
    harness.halt.assert_called()


@pytest.mark.asyncio
async def test_diagnostic_divergence_does_not_sync_or_clear(harness):
    harness.ledger.reconcile_with_kalshi_positions.return_value = {
        "status": "broken", "divergences": ["unknown fill"]
    }
    report = await harness.poller._do_reconcile()
    assert report["status"] == "error"
    harness.cache.sync_from_rest.assert_not_awaited()
    harness.cache.confirm_matched_rest_projection.assert_not_awaited()
    harness.ledger.clear_open_positions_on_empty_cache.assert_not_awaited()
    harness.halt.assert_called()


@pytest.mark.asyncio
async def test_matched_empty_snapshot_preserves_reservations(harness):
    report = await harness.poller._do_reconcile()
    assert report["status"] == "ok"
    harness.cache.confirm_matched_rest_projection.assert_awaited_once()
    harness.cache.sync_from_rest.assert_not_awaited()
    harness.ledger.clear_open_positions_on_empty_cache.assert_not_awaited()
    harness.halt.assert_not_called()


@pytest.mark.asyncio
async def test_cache_change_during_reconciliation_halts(harness):
    harness.cache.confirm_matched_rest_projection.side_effect = RuntimeError("cache changed")
    report = await harness.poller._do_reconcile()
    assert report["status"] == "error"
    assert "cache changed" in report["message"]
    harness.cache.sync_from_rest.assert_not_awaited()
    harness.halt.assert_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("drift_event", [False, True])
async def test_drift_failure_halts_without_touching_cache(harness, monkeypatch, drift_event):
    fill = SimpleNamespace(
        market_ticker="BTC", canonicalization_state="TRUSTED_LIVE_V1", is_live=True,
        fill_id="fill1", order_id="order1", client_order_id="client1",
        quantity_cc=123, canonical_yes_delta_cc=123,
        canonical_position_action="buy", canonical_position_side="yes",
    )
    harness.ledger.get_canonical_fills.return_value.authoritative = [fill]
    harness.ledger.compute_position_from_fills_async = AsyncMock(return_value={
        "contracts": Decimal("1.23"), "quantity_cc": 123,
    })
    harness.cache.get_all_positions.return_value = {
        "BTC": SimpleNamespace(market_id="BTC", thesis_side="yes", quantity_cc=123)
    }
    harness.cache.get_position = Mock(return_value=None)
    harness.client.get_positions.return_value = SimpleNamespace(positions=[
        Position(ticker="BTC", outcome="yes", size=Decimal("1.23"), average_entry_price_cents=50)
    ])
    check_drift = (
        AsyncMock(return_value=SimpleNamespace(
            severity=SimpleNamespace(value="critical"), description="drift detected"
        ))
        if drift_event else AsyncMock(side_effect=RuntimeError("drift unavailable"))
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.position_drift_detector.get_position_drift_detector",
        lambda: SimpleNamespace(check_drift=check_drift),
    )
    active_recon = SimpleNamespace(handle_violation=AsyncMock())
    monkeypatch.setattr(
        "merid.event_venues.kalshi.active_reconciliation.get_active_reconciliation",
        lambda: active_recon,
    )
    report = await harness.poller._do_reconcile()
    assert report["status"] == "error"
    assert ("drift detected" if drift_event else "drift unavailable") in report["message"]
    harness.cache.confirm_matched_rest_projection.assert_not_awaited()
    harness.halt.assert_called()


@pytest.mark.asyncio
async def test_missing_market_does_not_suppress_later_settlement_retry(harness, monkeypatch):
    import threading

    class MarketNotFound(Exception):
        status_code = 404

    harness.client.get_market = AsyncMock(side_effect=MarketNotFound("not found"))
    tracker = SimpleNamespace(_fill_lock=threading.Lock(), _open_trades={})
    monkeypatch.setattr(
        "merid.prediction.agent_performance_tracker.get_agent_performance_tracker",
        lambda: tracker,
    )
    await harness.poller._fire_settlement_outcomes(harness.client, ["KXBTC15M-26NOV011000-00"])
    assert "KXBTC15M-26NOV011000-00" not in harness.poller._settlement_notified


@pytest.mark.asyncio
async def test_cache_confirmation_is_atomic_and_never_rebuilds(monkeypatch):
    from merid.event_venues.kalshi.position_cache import KalshiPositionCache

    monkeypatch.setattr("merid.preflight.p0._reconciliation_quarantined", lambda ticker: False)
    cache = object.__new__(KalshiPositionCache)
    cache._mutex = asyncio.Lock()
    cache._positions = {"BTC": {"market_id": "BTC", "side": "yes", "quantity_cc": 123}}
    cache._last_sync = None
    cache._last_rest_sync_timestamp = 0.0

    with pytest.raises(RuntimeError, match="changed"):
        await cache.confirm_matched_rest_projection({"BTC": -123}, 1.0)
    assert cache._last_sync is None
    assert cache._positions["BTC"]["quantity_cc"] == 123
    await cache.confirm_matched_rest_projection({"BTC": 123}, 2.0)
    assert cache._last_rest_sync_timestamp == 2.0
    with pytest.raises(RuntimeError, match="not newer"):
        await cache.confirm_matched_rest_projection({"BTC": 123}, 1.0)


@pytest.mark.asyncio
async def test_failed_reconcile_cannot_mark_poller_ready(harness, monkeypatch):
    poller = harness.poller
    poller._shutdown = asyncio.Event()
    poller._restore_done = True
    real_sleep = asyncio.sleep

    async def no_delay(_seconds):
        await real_sleep(0)

    async def failed_reconcile():
        poller._shutdown.set()
        return {"status": "error", "message": "incomplete"}

    monkeypatch.setattr(asyncio, "sleep", no_delay)
    monkeypatch.setattr(poller, "_do_reconcile", failed_reconcile)
    await poller._reconcile_loop()
    assert poller._readiness == "DEGRADED"
    assert not poller._first_reconcile_done
    harness.halt.assert_called()
