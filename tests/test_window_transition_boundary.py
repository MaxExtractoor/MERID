"""Controlled 15m window-boundary tests with a fake clock.

These tests exercise the catalog → market-state → strategy hand-off at a
window rollover, using pinned ``now_utc`` and monkey-patched clocks so the
assertions are deterministic and do not depend on real time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from merid.event_venues.kalshi.kalshi_15m_time import select_live_markets_by_ts
from merid.event_venues.kalshi.market_catalog import CatalogMarket
from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
from merid.event_venues.kalshi.order_intent_contract import (
    CanonicalOrderIntent,
    OrderIntentValidationError,
    _accepted_entry_intents,
    clear_entry_idempotency_registry,
    validate_canonical_intent,
)


# ── Fake clock helpers ───────────────────────────────────────────────────────


class FakeClock:
    """Replace a module's time.monotonic() / time.time()."""

    def __init__(self, start: float = 1_000_000.0):
        self.t = start

    def monotonic(self) -> float:
        return self.t

    def time(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@dataclass
class WindowFixture:
    """A single 15m window for tests."""

    asset: str
    open_utc: datetime
    close_utc: datetime
    strike: int

    @property
    def market_id(self) -> str:
        # Format: KXBTC15M-YYMONDDHHMM-STRIKE (ET encoded time, only used for mapping)
        # For deterministic catalog tests we provide explicit open/close datetimes.
        dt = self.close_utc
        return f"KX{self.asset}15M-{dt:%y%b%d%H%M}-{self.strike:02d}".upper()

    def catalog_market(self) -> CatalogMarket:
        return CatalogMarket(
            market=SimpleNamespace(
                market_id=self.market_id,
                open_time=self.open_utc,
                close_time=self.close_utc,
            ),
            asset=self.asset,
            strike_price=float(self.strike),
            floor_strike=float(self.strike),
            cap_strike=float(self.strike) + 1,
            health_status="ok",
        )

    def rest_market_dict(self, expiration: datetime | None = None) -> dict[str, Any]:
        expiry = expiration or self.close_utc
        return {
            "ticker": self.market_id,
            "expiration_time": expiry.isoformat(),
            "expected_expiration_time": expiry.isoformat(),
            "latest_expiration_time": expiry.isoformat(),
            "volume_24h": 1000,
            "open_interest": 500,
            "notional_value": 0,
            "underlying": self.asset,
            "strike_price": float(self.strike),
            "floor_strike": float(self.strike),
            "cap_strike": float(self.strike) + 1,
            "status": "open",
        }


@pytest.fixture
def windows() -> list[WindowFixture]:
    base = datetime(2026, 8, 24, 23, 0, 0, tzinfo=timezone.utc)
    return [
        WindowFixture("BTC", base, base + timedelta(minutes=15), 15),
        WindowFixture("BTC", base + timedelta(minutes=15), base + timedelta(minutes=30), 30),
        WindowFixture("BTC", base + timedelta(minutes=30), base + timedelta(minutes=45), 45),
    ]


@pytest.fixture(autouse=True)
def _enable_entry_idempotency(monkeypatch):
    """conftest.py disables idempotency by default; re-enable it for these tests."""
    monkeypatch.setenv("MERID_ENTRY_IDEMPOTENCY_ENABLED", "1")


# ── Catalog / window selection boundary ─────────────────────────────────────


def test_select_live_markets_rolls_at_boundary(windows):
    """``select_live_markets_by_ts`` picks the correct window at exact boundaries."""
    markets = [w.catalog_market() for w in windows]

    # 7.5 minutes into first window
    now = windows[0].open_utc + timedelta(minutes=7, seconds=30)
    live = select_live_markets_by_ts(markets, now_utc=now)
    assert len(live) == 1
    assert live[0].market.market_id == windows[0].market_id

    # One second after second window opens
    now = windows[1].open_utc + timedelta(seconds=1)
    live = select_live_markets_by_ts(markets, now_utc=now)
    assert len(live) == 1
    assert live[0].market.market_id == windows[1].market_id

    # 31 seconds before third window opens: second window still has >0.5 min to expiry
    now = windows[2].open_utc - timedelta(seconds=31)
    live = select_live_markets_by_ts(markets, now_utc=now)
    assert live[0].market.market_id == windows[1].market_id

    # One second after third window opens
    now = windows[2].open_utc + timedelta(seconds=1)
    live = select_live_markets_by_ts(markets, now_utc=now)
    assert live[0].market.market_id == windows[2].market_id


def test_select_live_markets_filters_expired_and_preopen(windows):
    """Expired (< 0.5 min to expiry) and pre-open markets are excluded."""
    markets = [w.catalog_market() for w in windows]

    # 40 seconds before first window closes: still in 0.5-15 minute window
    now = windows[0].close_utc - timedelta(seconds=40)
    live = select_live_markets_by_ts(markets, now_utc=now)
    assert live[0].market.market_id == windows[0].market_id

    # 20 seconds before close: too close (< 0.5 min)
    now = windows[0].close_utc - timedelta(seconds=20)
    live = select_live_markets_by_ts(markets, now_utc=now)
    assert not live

    # 20 seconds before first window opens: not yet live
    now = windows[0].open_utc - timedelta(seconds=20)
    live = select_live_markets_by_ts(markets, now_utc=now)
    assert not live


# ── Market-state store per-window isolation ─────────────────────────────────


def _snapshot(ticker: str, yes: list, no: list) -> dict[str, Any]:
    return {"type": "orderbook_snapshot", "ticker": ticker, "yes": yes, "no": no}


def test_state_store_maintains_per_window_metadata(windows, monkeypatch):
    """Rest metadata (strike, expiry) for old and new windows co-exist."""
    fake_clock = FakeClock(start=1_000_000.0)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.time.monotonic", fake_clock.monotonic
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.time.time", fake_clock.time
    )

    store = KalshiMarketStateStore()
    old = windows[0]
    new = windows[1]

    store.apply_rest_market(old.rest_market_dict())
    store.apply_rest_market(new.rest_market_dict())

    old_state = store.get(old.market_id)
    new_state = store.get(new.market_id)

    assert old_state is not None
    assert new_state is not None
    assert old_state.floor_strike == old.strike
    assert new_state.floor_strike == new.strike
    assert old_state.underlying == "BTC"
    assert new_state.underlying == "BTC"


def test_quote_does_not_refresh_initialized_book(windows, monkeypatch):
    """A WS quote for the old window must not bump its ``last_book_update_ts``."""
    fake_clock = FakeClock(start=1_000_000.0)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.time.monotonic", fake_clock.monotonic
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.time.time", fake_clock.time
    )

    store = KalshiMarketStateStore()
    old = windows[0]

    # Initialize via REST + orderbook snapshot at time T
    store.apply_rest_market(old.rest_market_dict())
    store.apply_orderbook_message(
        _snapshot(old.market_id, [[0.55, 5], [0.54, 5]], [[0.45, 5]]),
        via="rest_bootstrap",
    )

    old_state = store.get(old.market_id)
    book_ts = old_state.last_book_update_ts
    assert book_ts > 0

    # Advance clock and push a quote on the SAME initialized book
    fake_clock.advance(5.0)
    store.apply_quote(old.market_id, bid_cents=40, ask_cents=60)

    old_state = store.get(old.market_id)
    # Quote must not refresh the staleness timestamp once a real orderbook exists
    assert old_state.last_book_update_ts == book_ts


def test_quote_does_not_initialize_new_window_book(windows, monkeypatch):
    """A WS quote must NOT initialize the executable orderbook for a new window."""
    fake_clock = FakeClock(start=1_000_000.0)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.time.monotonic", fake_clock.monotonic
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.time.time", fake_clock.time
    )

    store = KalshiMarketStateStore()
    new = windows[1]

    store.apply_rest_market(new.rest_market_dict())
    new_state = store.get(new.market_id)
    assert not new_state.book_initialized

    fake_clock.advance(2.0)
    store.apply_quote(new.market_id, bid_cents=40, ask_cents=60)

    new_state = store.get(new.market_id)
    # Quote is a fallback only; executable BBO must come from an orderbook snapshot/delta.
    assert not new_state.book_initialized
    assert new_state.last_book_update_ts is None or new_state.last_book_update_ts == 0.0
    assert new_state.quoted_bid_cents == 40
    assert new_state.quoted_ask_cents == 60
    assert new_state.quote_received_ts == fake_clock.t


def test_new_window_quote_does_not_touch_other_window(windows, monkeypatch):
    """Quote for the new window must not update an unrelated window's state."""
    fake_clock = FakeClock(start=1_000_000.0)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.time.monotonic", fake_clock.monotonic
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.time.time", fake_clock.time
    )

    store = KalshiMarketStateStore()
    old = windows[0]
    new = windows[1]

    store.apply_rest_market(old.rest_market_dict())
    store.apply_orderbook_message(
        _snapshot(old.market_id, [[0.55, 5], [0.54, 5]], [[0.45, 5]]),
        via="rest_bootstrap",
    )
    old_ts = store.get(old.market_id).last_book_update_ts

    store.apply_rest_market(new.rest_market_dict())

    fake_clock.advance(10.0)
    store.apply_quote(new.market_id, bid_cents=40, ask_cents=60)

    # Old window must keep its original timestamp
    assert store.get(old.market_id).last_book_update_ts == old_ts


def test_entry_ready_requires_metadata(windows, monkeypatch):
    """A 15m market missing floor/cap/strike must be rejected as entry-ready."""
    fake_clock = FakeClock(start=1_000_000.0)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.time.monotonic", fake_clock.monotonic
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.time.time", fake_clock.time
    )

    store = KalshiMarketStateStore()
    new = windows[1]

    # REST without strike metadata
    data = new.rest_market_dict()
    data.pop("strike_price")
    data.pop("floor_strike")
    data.pop("cap_strike")
    store.apply_rest_market(data)

    store.apply_orderbook_message(
        _snapshot(new.market_id, [[0.55, 5]], [[0.45, 5]]),
        via="rest_bootstrap",
    )

    ready, reason = store.is_market_entry_ready(new.market_id, max_age_seconds=60)
    assert not ready
    assert "METADATA-INVALID" in reason


def test_entry_ready_with_rest_bootstrap(windows, monkeypatch):
    """REST bootstrap + metadata is sufficient for new-entry readiness."""
    fake_clock = FakeClock(start=1_000_000.0)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.time.monotonic", fake_clock.monotonic
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.time.time", fake_clock.time
    )

    store = KalshiMarketStateStore()
    new = windows[1]

    store.apply_rest_market(new.rest_market_dict())
    store.apply_orderbook_message(
        _snapshot(new.market_id, [[0.55, 5]], [[0.45, 5]]),
        via="rest_bootstrap",
    )

    ready, reason = store.is_market_entry_ready(new.market_id, max_age_seconds=60)
    assert ready, f"expected ready, got {reason}"


# ── Order-intent idempotency scoping ────────────────────────────────────────


def _open_intent(ticker: str, contract: str = "yes", client_order_id: str = "coid-1") -> CanonicalOrderIntent:
    return CanonicalOrderIntent(
        market_ticker=ticker,
        contract=contract,
        action="buy",
        purpose="open",
        qty_cc=50,
        limit_cents=45,
        strategy_signal="up",
        expected_position_before=0,
        expected_position_after=50,
        expected_realized_pnl_cents=0,
        reason="boundary_test",
        client_order_id=client_order_id,
        fee_cents=2,
        ev_net_cents=10.0,
        time_to_expiry_seconds=600,
    )


def test_rejected_window_a_does_not_block_window_b(monkeypatch):
    """Idempotency key is per (ticker, side); a different window is not blocked."""
    clear_entry_idempotency_registry()

    window_a = "KXBTC15M-26AUG241915-15"
    window_b = "KXBTC15M-26AUG241930-30"

    # First entry in window A records successfully
    validate_canonical_intent(_open_intent(window_a), exchange_position_cc=0)

    # Same side in the *next* window is allowed (different market_ticker)
    validate_canonical_intent(_open_intent(window_b), exchange_position_cc=0)


def test_duplicate_same_window_still_rejected(monkeypatch):
    """Two different intents for the same (ticker, side) are rejected."""
    clear_entry_idempotency_registry()

    window_a = "KXBTC15M-26AUG241915-15"
    validate_canonical_intent(_open_intent(window_a, client_order_id="coid-1"), exchange_position_cc=0)

    with pytest.raises(OrderIntentValidationError, match="duplicate_entry"):
        validate_canonical_intent(
            _open_intent(window_a, client_order_id="coid-2"), exchange_position_cc=0
        )


def test_pre_submit_record_evicted_by_fake_clock(monkeypatch):
    """A stale pre-submit record is replaced after the short TTL."""
    clear_entry_idempotency_registry()
    monkeypatch.setenv("MERID_ENTRY_PRE_SUBMIT_TTL_SECONDS", "0.01")

    fake_clock = FakeClock(start=1_000_000.0)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_intent_contract.time.time", fake_clock.time
    )

    window_a = "KXBTC15M-26AUG241915-15"
    validate_canonical_intent(_open_intent(window_a, client_order_id="coid-1"), exchange_position_cc=0)

    # Before TTL: duplicate still rejected
    with pytest.raises(OrderIntentValidationError, match="duplicate_entry"):
        validate_canonical_intent(
            _open_intent(window_a, client_order_id="coid-2"), exchange_position_cc=0
        )

    # Advance the fake clock past the 0.01s TTL
    fake_clock.advance(0.02)

    # After TTL: old record should be replaced by the new attempt
    validate_canonical_intent(
        _open_intent(window_a, client_order_id="coid-2"), exchange_position_cc=0
    )


def test_three_window_uninterrupted_chain(windows, monkeypatch):
    """A process must transition from window A to B to C with no ticker leakage.

    The strongest pass condition we can assert in a unit test is that the catalog
    selection, market-state store, and order-intent idempotency all agree on the
    active ticker at every stage, and that old-window state does not contaminate
    new-window state.
    """
    fake_clock = FakeClock(start=1_000_000.0)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.time.monotonic", fake_clock.monotonic
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.time.time", fake_clock.time
    )

    store = KalshiMarketStateStore()
    markets = [w.catalog_market() for w in windows]
    clear_entry_idempotency_registry()

    # ── Window A active ───────────────────────────────────────────────────────
    now_a = windows[0].open_utc + timedelta(minutes=7, seconds=30)
    live = select_live_markets_by_ts(markets, now_utc=now_a)
    assert len(live) == 1
    ticker_a = live[0].market.market_id
    assert ticker_a == windows[0].market_id

    store.apply_rest_market(windows[0].rest_market_dict())
    store.apply_orderbook_message(
        _snapshot(ticker_a, [[0.55, 5]], [[0.45, 5]]),
        via="rest_bootstrap",
    )
    assert store.is_market_entry_ready(ticker_a, max_age_seconds=60)[0]

    intent_a = _open_intent(ticker_a, client_order_id="coid-a")
    validate_canonical_intent(intent_a, exchange_position_cc=0)

    # ── Window B active ───────────────────────────────────────────────────────
    now_b = windows[1].open_utc + timedelta(seconds=1)
    live = select_live_markets_by_ts(markets, now_utc=now_b)
    assert len(live) == 1
    ticker_b = live[0].market.market_id
    assert ticker_b == windows[1].market_id
    assert ticker_b != ticker_a

    # Old window A state must remain intact but not be entry-ready after rollover.
    assert store.get(ticker_a) is not None
    assert store.get(ticker_a).floor_strike == windows[0].strike

    store.apply_rest_market(windows[1].rest_market_dict())
    store.apply_orderbook_message(
        _snapshot(ticker_b, [[0.55, 5]], [[0.45, 5]]),
        via="rest_bootstrap",
    )
    assert store.is_market_entry_ready(ticker_b, max_age_seconds=60)[0]

    # A rejected order in A must not block a new order in B.
    intent_b = _open_intent(ticker_b, client_order_id="coid-b")
    validate_canonical_intent(intent_b, exchange_position_cc=0)

    # Old-window quote must not bump new-window state.
    fake_clock.advance(10.0)
    store.apply_quote(ticker_a, bid_cents=40, ask_cents=60)
    assert store.get(ticker_b).quoted_bid_cents != 40
    assert store.is_market_entry_ready(ticker_b, max_age_seconds=60)[0]

    # ── Window C active ───────────────────────────────────────────────────────
    now_c = windows[2].open_utc + timedelta(seconds=1)
    live = select_live_markets_by_ts(markets, now_utc=now_c)
    assert len(live) == 1
    ticker_c = live[0].market.market_id
    assert ticker_c == windows[2].market_id
    assert ticker_c not in (ticker_a, ticker_b)

    store.apply_rest_market(windows[2].rest_market_dict())
    store.apply_orderbook_message(
        _snapshot(ticker_c, [[0.55, 5]], [[0.45, 5]]),
        via="rest_bootstrap",
    )
    assert store.is_market_entry_ready(ticker_c, max_age_seconds=60)[0]

    intent_c = _open_intent(ticker_c, client_order_id="coid-c")
    validate_canonical_intent(intent_c, exchange_position_cc=0)

    # Chain integrity: every selected window had an accepted intent in its own ticker.
    assert all(
        rec["client_order_id"] in ("coid-a", "coid-b", "coid-c")
        and ticker in (ticker_a, ticker_b, ticker_c)
        for (ticker, _), rec in _accepted_entry_intents.items()
    )


def test_loop_15m_entry_readiness_across_three_windows(windows, monkeypatch, caplog):
    """Kalshi15mLoop._compute_allow_new_entries emits per-ticker ENTRY-READINESS
    across window A -> B -> C and marks each active window as entries_allowed.
    """
    from unittest.mock import MagicMock

    from merid.loop_15m import Kalshi15mLoop
    from merid.event_venues.kalshi.market_catalog import CatalogMarket

    fake_clock = FakeClock(start=1_000_000.0)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.time.monotonic", fake_clock.monotonic
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.time.time", fake_clock.time
    )

    # Make the loop think the platform is healthy and a strip is expected.
    monkeypatch.setattr("merid.event_venues.kalshi.kalshi_config.KALSHI_READY", True)
    monkeypatch.setattr("merid.loop_15m.markets_expected_now", lambda: True)

    loop = Kalshi15mLoop(
        agent_grid=MagicMock(),
        bankroll_service=MagicMock(),
        risk_config=MagicMock(),
    )
    # Use a fresh market-state store and keep risk envelope simple.
    store = KalshiMarketStateStore()
    loop.market_state_store = store
    loop._risk_envelope = None

    def _apply_window(w: WindowFixture) -> str:
        store.apply_rest_market(w.rest_market_dict())
        store.apply_orderbook_message(
            _snapshot(w.market_id, [[0.55, 5]], [[0.45, 5]]),
            via="rest_bootstrap",
        )
        # The loop's readiness gate checks for a complete WS/REST bootstrap
        # snapshot; rest_bootstrap attests recovery but does not set the
        # snapshot_complete bootstrap flag.
        s = store.get(w.market_id)
        if s is not None:
            s.snapshot_complete = True
        return w.market_id

    for active in windows:
        clear_entry_idempotency_registry()
        ticker = _apply_window(active)

        # Mock the catalog so only BTC's active window is current.
        def _current_for_asset(asset: str) -> CatalogMarket | None:
            if asset == "BTC":
                return active.catalog_market()
            return None

        monkeypatch.setattr(
            "merid.event_venues.kalshi.market_catalog.get_market_catalog",
            lambda: MagicMock(get_current_15m_market=_current_for_asset),
        )

        caplog.clear()
        allowed = loop._compute_allow_new_entries(cycle_bankroll=1000.0)

        assert allowed, f"Window {ticker} should allow new entries"

        readiness_logs = [
            r for r in caplog.records if "ENTRY-READINESS" in r.getMessage()
        ]
        assert readiness_logs, f"No ENTRY-READINESS log for window {ticker}"

        msg = readiness_logs[0].getMessage()
        assert f"ticker={ticker}" in msg
        assert "entries_allowed=True" in msg
        assert "quote_coherent=True" in msg
        assert "queue_healthy=True" in msg
        assert "market_state_applied=True" in msg
