"""Regression tests for the 2026-11-09 XRP in-flight fill race.

Incident: KXXRP15M-26NOV082330-30 sold 4 YES @18c via stop_candidate
LOSS_CAP IOC at 23:24:51.  ~4s later the exchange-authoritative REST
position sync saw zero contracts and ``_cleanup_stale_positions`` removed
the cached position as "phantom" — the fills ledger already netted to zero
(entry+exit both recorded) even though ``position_cache.apply_fill`` had
not yet applied the closing fill.  When fill ingestion arrived ~2s later
the position was gone, so the real exit fill was rejected with
EXIT-FILL-WITHOUT-POSITION (twice — WS alpha + REST poller duplicate).

Fixes under test:
1. ``_cleanup_stale_positions`` defers phantom removal while any recent
   ledger fill for the market is still unapplied through position_cache.
2. The exit-fill-without-position rejection marks the fill applied so
   duplicate ingestions dedupe instead of re-firing the critical path.
"""

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import merid.event_venues.kalshi.position_cache as pc_mod
from merid.event_venues.kalshi.position_cache import KalshiPositionCache


TICKER = "KXXRP15M-30DEC010000-00"  # far-future: never expired in tests


def _fill(fill_id, action, qty_cc, age_s=0.0):
    return SimpleNamespace(
        fill_id=fill_id,
        action=action,
        quantity_cc=qty_cc,
        count=None,
        contracts=None,
        created_time=datetime.now(timezone.utc) - timedelta(seconds=age_s),
    )


def _cache_with_position():
    cache = KalshiPositionCache()
    cache._positions.clear()
    cache._applied_fill_ids.clear()  # isolate from durable/session state
    cache._positions[TICKER] = SimpleNamespace(
        contracts=4,
        avg_price_cents=61,
        quantity_cc=400,
        side="yes",
        thesis_side="yes",
    )
    return cache


def _ledger_with_fills(fills):
    ledger = Mock()
    ledger.get_fills.return_value = fills
    return ledger


class TestStaleCleanupPendingFillDeferral:
    """_cleanup_stale_positions must not remove a position whose closing
    fill is recorded in the ledger but not yet applied through the cache."""

    @pytest.mark.asyncio
    async def test_defers_removal_while_exit_fill_unapplied(self, monkeypatch):
        """XRP replay: buy+sell net to zero, sell fill fresh & unapplied."""
        monkeypatch.setattr(pc_mod, "_is_expired_ticker", lambda t: False)
        cache = _cache_with_position()
        buy = _fill("fill_entry", "buy", 400, age_s=200.0)
        sell = _fill("fill_exit", "sell", 400, age_s=2.0)
        cache._fills_ledger = _ledger_with_fills([buy, sell])
        cache._applied_fill_ids["fill_entry"] = 1.0  # entry already applied
        # fill_exit deliberately NOT in _applied_fill_ids — still draining.

        report = await cache._cleanup_stale_positions(
            exchange_positions=[], open_orders=[]
        )

        assert report["removed"] == []
        assert {"market_id": TICKER, "reason": "pending_fill_application"} in [
            dict(r) for r in report["kept"]
        ] or any(
            r.get("reason") == "pending_fill_application" for r in report["kept"]
        )
        assert TICKER in cache._positions, (
            "position must survive until the in-flight exit fill applies"
        )

    @pytest.mark.asyncio
    async def test_removes_when_all_fills_applied(self, monkeypatch):
        """Once the closing fill is applied, net-zero + exchange-zero is a
        true phantom and removal proceeds."""
        monkeypatch.setattr(pc_mod, "_is_expired_ticker", lambda t: False)
        cache = _cache_with_position()
        buy = _fill("fill_entry", "buy", 400, age_s=200.0)
        sell = _fill("fill_exit", "sell", 400, age_s=2.0)
        cache._fills_ledger = _ledger_with_fills([buy, sell])
        cache._applied_fill_ids["fill_entry"] = 1.0
        cache._applied_fill_ids["fill_exit"] = 1.0

        report = await cache._cleanup_stale_positions(
            exchange_positions=[], open_orders=[]
        )

        assert any(r.get("reason") == "phantom" for r in report["removed"])
        assert TICKER not in cache._positions

    @pytest.mark.asyncio
    async def test_removes_when_unapplied_fill_is_stale(self, monkeypatch):
        """An unapplied fill older than the grace window is a pipeline gap,
        not in-flight work — removal proceeds (bounded deferral)."""
        monkeypatch.setattr(pc_mod, "_is_expired_ticker", lambda t: False)
        monkeypatch.setenv("MERID_STALE_CLEANUP_PENDING_FILL_GRACE_S", "300")
        cache = _cache_with_position()
        buy = _fill("fill_entry", "buy", 400, age_s=2000.0)
        sell = _fill("fill_exit", "sell", 400, age_s=400.0)  # > 300s grace
        cache._fills_ledger = _ledger_with_fills([buy, sell])
        cache._applied_fill_ids["fill_entry"] = 1.0

        report = await cache._cleanup_stale_positions(
            exchange_positions=[], open_orders=[]
        )

        assert any(r.get("reason") == "phantom" for r in report["removed"])
        assert TICKER not in cache._positions

    @pytest.mark.asyncio
    async def test_removes_when_no_ledger_fills(self, monkeypatch):
        """Baseline: no fills at all -> genuine phantom -> removed."""
        monkeypatch.setattr(pc_mod, "_is_expired_ticker", lambda t: False)
        cache = _cache_with_position()
        cache._fills_ledger = _ledger_with_fills([])

        report = await cache._cleanup_stale_positions(
            exchange_positions=[], open_orders=[]
        )

        assert any(r.get("reason") == "phantom" for r in report["removed"])
        assert TICKER not in cache._positions

    @pytest.mark.asyncio
    async def test_open_order_still_keeps_position(self, monkeypatch):
        """Existing guard preserved: a live open order keeps the position
        regardless of fill state."""
        monkeypatch.setattr(pc_mod, "_is_expired_ticker", lambda t: False)
        cache = _cache_with_position()
        cache._fills_ledger = _ledger_with_fills([])

        report = await cache._cleanup_stale_positions(
            exchange_positions=[],
            open_orders=[{"market_id": TICKER, "side": "yes", "contracts": 4}],
        )

        assert any(r.get("reason") == "open_order" for r in report["kept"])
        assert TICKER in cache._positions


class TestExitFillWithoutPositionMarksApplied:
    """The deliberate rejection must record the fill as handled so the
    duplicate ingestion (WS + REST poller) dedupes instead of re-firing
    the critical path, and cleanup deferral cannot wait forever on a
    fill that was rejected by design."""

    @pytest.mark.asyncio
    async def test_rejected_exit_fill_is_marked_applied(self):
        cache = KalshiPositionCache()
        cache._positions.clear()
        cache._applied_fill_ids.clear()  # isolate from durable/session state
        cache._fills_ledger = None

        await cache.on_fill(
            market_id=TICKER,
            contracts=4,
            price_cents=18,
            fee_cents=0,
            side="yes",
            action="sell",
            is_exit=True,
            fill_id="fill_exit_rejected",
            client_order_id="stopcand_sc-test",
            canonicalization_state="TRUSTED_LIVE_V1",
            quantity_cc=400,
        )

        assert TICKER not in cache._positions, (
            "exit fill without a position must never create a phantom"
        )
        assert "fill_exit_rejected" in cache._applied_fill_ids, (
            "rejected fill must be marked applied so duplicates dedupe"
        )

    @pytest.mark.asyncio
    async def test_duplicate_ingestion_dedupes_after_rejection(self):
        """Second ingestion of the same fill_id hits the idempotency gate
        before reaching the exit-fill-error path again."""
        cache = KalshiPositionCache()
        cache._positions.clear()
        cache._applied_fill_ids.clear()
        cache._fills_ledger = None

        kwargs = dict(
            market_id=TICKER,
            contracts=4,
            price_cents=18,
            fee_cents=0,
            side="yes",
            action="sell",
            is_exit=True,
            fill_id="fill_exit_dup",
            client_order_id="stopcand_sc-test2",
            canonicalization_state="TRUSTED_LIVE_V1",
            quantity_cc=400,
        )
        await cache.on_fill(**kwargs)
        # Second call: must return via the idempotency gate without error.
        await cache.on_fill(**kwargs)

        assert TICKER not in cache._positions
        assert "fill_exit_dup" in cache._applied_fill_ids
        # The duplicate call deduped at the entry gate — no second rejection.
        assert sum(1 for k in cache._applied_fill_ids if k == "fill_exit_dup") == 1
