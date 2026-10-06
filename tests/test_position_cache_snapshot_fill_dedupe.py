"""
Regression tests for snapshot/fill double-apply (2026-10-06 incident).

Live incident: a resting maker order filled at 00:03:43.  The fills_poller's
REST position sync at 00:04:06 reconstructed the position (recompute replayed
the canonical ledger fill -> cache=100).  The delayed canonical fill event then
arrived via fill_bus at 00:04:20 and applied +100 again -> cache=200 vs
exchange=100.  The reconciler healed it ~3min later, but exposure/risk math was
inflated in the interim.

Root causes fixed:
  1. Ledger-replay paths (sync_from_rest recompute, _rebuild_from_fills_ledger)
     reflected fills in cache state without marking them in _applied_fill_ids.
  2. REST-synced positions carried no "snapshot coverage" bound, so a delayed
     fill event could not prove the snapshot already contained it.

Contract under test: one economic fill -> exactly one exposure delta, for any
ordering of {router provisional, WS fill, HTTP fill, REST snapshot, ledger
replay}.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from merid.event_venues.kalshi.position_cache import (
    CachedPosition,
    KalshiPositionCache,
    _fill_created_time_dt,
)


TICKER = "KXBTC15M-26OCT052015-15"
T0 = datetime(2026, 10, 6, 0, 3, 43, tzinfo=timezone.utc)   # exchange fill time
SNAP_TS = (T0 + timedelta(seconds=22)).timestamp()          # REST snapshot fetch


def _cache(tmp_path, monkeypatch) -> KalshiPositionCache:
    monkeypatch.setenv("MERID_APPLIED_FILL_IDS_PATH", str(tmp_path / "applied.json"))
    # The fixture tickers use a fixed past window; keep them syncable.
    import merid.event_venues.kalshi.position_cache as pc_mod
    monkeypatch.setattr(pc_mod, "_is_expired_ticker", lambda _t: False)
    monkeypatch.setattr(pc_mod, "_is_test_ticker", lambda _t: False)
    KalshiPositionCache._instance = None
    cache = KalshiPositionCache()
    cache._positions.clear()
    cache._applied_fill_ids.clear()
    cache._reconciliation_halted.clear()
    # Neutralize the restart predate guard so tests exercise the REST-snapshot
    # coverage guard specifically (fixture fills use a fixed past timestamp).
    cache._started_at = 0.0
    return cache


def _ledger(*fills) -> Mock:
    ledger = Mock()
    by_id = {f.fill_id: f for f in fills}
    ledger.get_fill_by_id.side_effect = lambda fid: by_id.get(fid)
    ledger.get_fills_by_market.side_effect = lambda _m, **kw: list(fills)
    ledger.get_fills.side_effect = lambda **kw: list(fills)
    return ledger


def _fill(fill_id, *, created_time, side="yes", action="buy", qty_cc=100,
          order_id="ord-1", client_order_id="coid-1", is_exit=None, price=72):
    """Minimal KalshiFill stand-in with the fields the cache reads."""
    return SimpleNamespace(
        fill_id=fill_id,
        market_ticker=TICKER,
        market_id=TICKER,
        order_id=order_id,
        client_order_id=client_order_id,
        intent_id="intent-1",
        side=side,
        action=action,
        canonical_position_side=side,
        canonical_position_action=action,
        canonical_leg_price_cents=price,
        quantity_cc=qty_cc,
        count_fp=qty_cc / 100.0,
        price_cents=price,
        fee_cents=0,
        created_time=created_time,
        is_exit=is_exit,
        unmatched=False,
        is_live=True,
        agent_id="BTC_15M",
        exchange_index=2,
        proceeds_dollars=None,
        raw_payload="{}",
    )


def _rest_position(contracts=1, side="yes", avg=72):
    # Kalshi REST position_fp is signed YES exposure: negative for NO holdings.
    signed_fp = contracts if side == "yes" else -contracts
    return {
        "market_id": TICKER,
        "ticker": TICKER,
        "contracts": contracts,
        "position_fp": signed_fp,
        "side": side,
        "outcome_id": side,
        "avg_price_cents": avg,
        "average_price_cents": avg,
        "market_exposure_dollars": contracts * avg / 100.0,
    }


def _on_fill(cache, *, fill_id, action="buy", side="yes", contracts=1, price=72):
    return cache.on_fill(
        market_id=TICKER,
        contracts=contracts,
        price_cents=price,
        fee_cents=0,
        side=side,
        action=action,
        client_order_id="coid-1",
        fill_id=fill_id,
        canonicalization_state="TRUSTED_LIVE_V1",
    )


def _yes_exposure(cache):
    pos = cache._positions.get(TICKER)
    return pos._yes_exposure() if pos else 0


# ---------------------------------------------------------------------------
# 1. The incident replay: REST snapshot first, delayed canonical fill second.
# ---------------------------------------------------------------------------

def test_delayed_canonical_fill_after_rest_sync_does_not_double_apply(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)

    entry = _fill("fill-canon-1", created_time=T0)
    cache._fills_ledger = _ledger(entry)

    # REST sync reconstructs the 1-contract YES position from the snapshot.
    asyncio.run(cache.sync_from_rest(positions=[_rest_position()], rest_timestamp=SNAP_TS))
    assert _yes_exposure(cache) == 100
    assert cache._positions[TICKER].rest_synced_at is not None

    # The sync must mark the snapshot-covered fill applied...
    assert "fill-canon-1" in cache._applied_fill_ids

    # ...so when the delayed canonical fill event arrives it cannot re-apply.
    asyncio.run(_on_fill(cache, fill_id="fill-canon-1"))
    assert _yes_exposure(cache) == 100, "same economic fill mutated exposure twice"


def test_rest_only_position_covered_fill_skipped_without_ledger_mark(tmp_path, monkeypatch):
    """Snapshot built the position but the ledger lacks the fill at sync time;
    the fill then arrives late WITH a ledger record.  rest_synced_at alone must
    suppress the delta and migrate entry provenance."""
    cache = _cache(tmp_path, monkeypatch)

    # Ledger empty at sync time; the fill record only exists when on_fill runs.
    ledger = _ledger()
    entry = _fill("fill-late-1", created_time=T0)
    ledger.get_fill_by_id.side_effect = lambda fid: {"fill-late-1": entry}.get(fid)
    cache._fills_ledger = ledger

    asyncio.run(cache.sync_from_rest(positions=[_rest_position()], rest_timestamp=SNAP_TS))
    pos = cache._positions[TICKER]
    assert _yes_exposure(cache) == 100
    assert "fill-late-1" not in cache._applied_fill_ids   # not marked at sync

    asyncio.run(_on_fill(cache, fill_id="fill-late-1"))
    assert _yes_exposure(cache) == 100
    assert "fill-late-1" in cache._applied_fill_ids        # marked on skip
    assert pos.entry_fill_id == "fill-late-1"              # provenance migrated
    assert pos.entry_order_id == "ord-1"


def test_post_snapshot_fill_still_applies(tmp_path, monkeypatch):
    """A fill that executed AFTER the REST snapshot is not covered and must
    apply its delta normally (a real add-to-position / second fill)."""
    cache = _cache(tmp_path, monkeypatch)

    old = _fill("fill-old", created_time=T0)
    new = _fill("fill-new", created_time=T0 + timedelta(seconds=40))
    # At sync time the ledger knows only the old fill; get_fill_by_id resolves
    # both so the post-snapshot fill can be classified when it arrives.
    ledger = _ledger(old)
    ledger.get_fill_by_id.side_effect = lambda fid: {"fill-old": old, "fill-new": new}.get(fid)
    cache._fills_ledger = ledger

    asyncio.run(cache.sync_from_rest(positions=[_rest_position()], rest_timestamp=SNAP_TS))
    assert _yes_exposure(cache) == 100

    # New fill created 40s after the snapshot fetch -> must apply.
    asyncio.run(_on_fill(cache, fill_id="fill-new"))
    assert _yes_exposure(cache) == 200


def test_covered_exit_fill_does_not_get_stamped_as_entry(tmp_path, monkeypatch):
    """An exit fill predating the snapshot is covered too — it must skip its
    delta but never overwrite the position's entry provenance."""
    cache = _cache(tmp_path, monkeypatch)

    exit_fill = _fill("fill-exit-1", created_time=T0, action="sell", is_exit=True)
    cache._fills_ledger = _ledger(exit_fill)

    asyncio.run(cache.sync_from_rest(positions=[_rest_position()], rest_timestamp=SNAP_TS))
    pos = cache._positions[TICKER]
    pos.entry_fill_id = "fill-entry-real"
    assert _yes_exposure(cache) == 100

    # Exit fill predating the snapshot: the snapshot (still 1 contract) already
    # reflects whatever the exchange had executed — skip the delta.
    asyncio.run(_on_fill(cache, fill_id="fill-exit-1", action="sell"))
    assert _yes_exposure(cache) == 100
    assert pos.entry_fill_id == "fill-entry-real"          # not overwritten


def test_no_side_covered_fill_skipped(tmp_path, monkeypatch):
    """Same coverage semantics on the NO side (signed YES exposure < 0)."""
    cache = _cache(tmp_path, monkeypatch)

    entry = _fill("fill-no-1", created_time=T0, side="no", action="buy", price=30)
    cache._fills_ledger = _ledger(entry)

    asyncio.run(cache.sync_from_rest(
        positions=[_rest_position(contracts=1, side="no", avg=30)],
        rest_timestamp=SNAP_TS,
    ))
    assert _yes_exposure(cache) == -100

    asyncio.run(_on_fill(cache, fill_id="fill-no-1", side="no", price=30))
    assert _yes_exposure(cache) == -100


# ---------------------------------------------------------------------------
# 2. _rebuild_from_fills_ledger marks replayed fills applied.
# ---------------------------------------------------------------------------

def test_rebuild_marks_replayed_fills_applied(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)

    entry = _fill("fill-replay-1", created_time=T0)
    cache._fills_ledger = _ledger(entry)

    asyncio.run(cache._rebuild_from_fills_ledger())
    assert _yes_exposure(cache) == 100
    assert "fill-replay-1" in cache._applied_fill_ids

    # A delayed event for the replayed fill cannot double-apply.
    asyncio.run(_on_fill(cache, fill_id="fill-replay-1"))
    assert _yes_exposure(cache) == 100


def test_rebuild_flat_market_marks_both_legs(tmp_path, monkeypatch):
    """Entry+exit replaying to flat: both legs are reflected in the (empty)
    state — a re-delivered entry fill must not ghost a closed position."""
    cache = _cache(tmp_path, monkeypatch)

    entry = _fill("fill-e", created_time=T0)
    exit_ = _fill("fill-x", created_time=T0 + timedelta(seconds=10), action="sell", is_exit=True)
    cache._fills_ledger = _ledger(entry, exit_)

    asyncio.run(cache._rebuild_from_fills_ledger())
    assert _yes_exposure(cache) == 0
    assert {"fill-e", "fill-x"} <= set(cache._applied_fill_ids)

    asyncio.run(_on_fill(cache, fill_id="fill-e"))
    assert _yes_exposure(cache) == 0, "re-delivered entry ghosted a closed position"


# ---------------------------------------------------------------------------
# 3. Ordering: fill event first, snapshot second (already-safe direction).
# ---------------------------------------------------------------------------

def test_fill_first_then_snapshot_remains_consistent(tmp_path, monkeypatch):
    """Canonical fill applies first; a later REST snapshot replaces the state
    with the same absolute quantity.  A redelivery of the fill stays skipped."""
    cache = _cache(tmp_path, monkeypatch)

    entry = _fill("fill-first-1", created_time=T0)
    cache._fills_ledger = _ledger(entry)

    asyncio.run(_on_fill(cache, fill_id="fill-first-1"))
    assert _yes_exposure(cache) == 100
    assert "fill-first-1" in cache._applied_fill_ids

    # REST snapshot arrives later and still reports the same 1 contract.
    asyncio.run(cache.sync_from_rest(
        positions=[_rest_position()],
        rest_timestamp=(T0 + timedelta(seconds=30)).timestamp(),
    ))
    assert _yes_exposure(cache) == 100

    # Transport-level redelivery of the same fill: idempotent.
    asyncio.run(_on_fill(cache, fill_id="fill-first-1"))
    assert _yes_exposure(cache) == 100


def test_partial_fill_then_remaining_canonical_still_applies(tmp_path, monkeypatch):
    """Two distinct fills for the same market: the one predating the snapshot
    is covered; a second (post-snapshot) partial must still apply."""
    cache = _cache(tmp_path, monkeypatch)

    part1 = _fill("fill-p1", created_time=T0, qty_cc=50)
    part2 = _fill("fill-p2", created_time=T0 + timedelta(seconds=60), qty_cc=50)
    ledger = _ledger(part1)
    ledger.get_fill_by_id.side_effect = lambda fid: {"fill-p1": part1, "fill-p2": part2}.get(fid)
    cache._fills_ledger = ledger

    asyncio.run(cache.sync_from_rest(
        positions=[_rest_position(contracts=1)],   # exchange shows 1 (p1+p2 executed; p2's created_time is post-snapshot though)
        rest_timestamp=SNAP_TS,
    ))
    assert _yes_exposure(cache) == 100
    assert "fill-p1" in cache._applied_fill_ids

    # p2's exchange created_time is AFTER the snapshot -> not covered -> applies.
    # (This is the edge where snapshot qty may already include it; the
    # reconciler owns that residual — the guard must not block it.)
    asyncio.run(_on_fill(cache, fill_id="fill-p2", contracts=0.5))
    assert _yes_exposure(cache) == 150


# ---------------------------------------------------------------------------
# 4. Helper unit tests.
# ---------------------------------------------------------------------------

def test_fill_created_time_dt_parsing():
    f = _fill("x", created_time=T0)
    assert _fill_created_time_dt(f) == T0
    f_str = _fill("y", created_time="2026-10-06T00:03:43Z")
    assert _fill_created_time_dt(f_str) == T0
    assert _fill_created_time_dt(None) is None
    assert _fill_created_time_dt(_fill("z", created_time=None)) is None
    naive = _fill("n", created_time=T0.replace(tzinfo=None))
    assert _fill_created_time_dt(naive) == T0  # treated as UTC
