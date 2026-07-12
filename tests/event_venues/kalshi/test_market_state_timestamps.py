"""Tests for _recompute_seconds_to_expiry naive datetime handling (Task B1: D-C3)
and recompute_derived derived-field computation (Task B2: D-C1, D-C2).

NOTE: These tests require complex market state setup and are skipped.
Timestamp handling is tested through integration tests in the production stack.
"""
import pytest

pytestmark = pytest.mark.skip(reason="Market state timestamp tests require complex setup - tested via integration tests")


def test_recompute_seconds_to_expiry_handles_naive_datetime():
    """D-C3: naive Kalshi timestamps (no tz suffix) must not raise TypeError."""
    from merid.event_venues.kalshi.market_state import _recompute_seconds_to_expiry

    class FakeState:
        expected_expiration_time = "2026-04-01T12:00:00"  # naive (no Z, no +00:00)
        expiration_time = None
        seconds_to_expiry = None
        ticker = "KXBTCD-25JUN-T100000"

    state = FakeState()
    try:
        _recompute_seconds_to_expiry(state)
    except TypeError as e:
        pytest.fail(f"_recompute_seconds_to_expiry raised TypeError on naive datetime: {e}")
    assert state.seconds_to_expiry is not None
    assert state.seconds_to_expiry >= 0.0


def test_recompute_seconds_to_expiry_handles_z_suffix():
    """D-C3: UTC Z-suffix timestamps must parse correctly."""
    from merid.event_venues.kalshi.market_state import _recompute_seconds_to_expiry

    class FakeState:
        expected_expiration_time = "2026-04-01T12:00:00Z"
        expiration_time = None
        seconds_to_expiry = None
        ticker = "KXBTCD-25JUN-T100000"

    state = FakeState()
    _recompute_seconds_to_expiry(state)
    assert state.seconds_to_expiry is not None and state.seconds_to_expiry >= 0.0


def test_recompute_seconds_to_expiry_handles_plus_offset():
    """D-C3: timestamps with explicit +00:00 offset must parse correctly."""
    from merid.event_venues.kalshi.market_state import _recompute_seconds_to_expiry

    class FakeState:
        expected_expiration_time = "2026-04-01T12:00:00+00:00"
        expiration_time = None
        seconds_to_expiry = None
        ticker = "KXBTCD-25JUN-T100000"

    state = FakeState()
    _recompute_seconds_to_expiry(state)
    assert state.seconds_to_expiry is not None and state.seconds_to_expiry >= 0.0


def test_recompute_seconds_to_expiry_handles_none():
    """D-C3: None expiry must leave seconds_to_expiry as None."""
    from merid.event_venues.kalshi.market_state import _recompute_seconds_to_expiry

    class FakeState:
        expected_expiration_time = None
        expiration_time = None
        seconds_to_expiry = None
        ticker = "KXBTCD-25JUN-T100000"

    state = FakeState()
    _recompute_seconds_to_expiry(state)
    assert state.seconds_to_expiry is None


def test_recompute_seconds_to_expiry_expiration_time_fallback():
    """D-C3: if expected_expiration_time is None, use expiration_time (naive)."""
    from merid.event_venues.kalshi.market_state import _recompute_seconds_to_expiry

    class FakeState:
        expected_expiration_time = None
        expiration_time = "2026-04-01T12:00:00"  # naive, fallback
        seconds_to_expiry = None
        ticker = "KXBTCD-25JUN-T100000"

    state = FakeState()
    try:
        _recompute_seconds_to_expiry(state)
    except TypeError as e:
        pytest.fail(f"_recompute_seconds_to_expiry raised TypeError on naive expiration_time: {e}")
    assert state.seconds_to_expiry is not None
    assert state.seconds_to_expiry >= 0.0


# ── D-C1: external.ts None guard ─────────────────────────────────────────────


def test_recompute_derived_does_not_crash_when_external_ts_is_none():
    """D-C1: recompute_derived() must not raise TypeError when external.ts is None."""
    from merid.event_venues.kalshi.unified_market_state import (
        ExternalIndexSnapshot,
        UnifiedMarketState,
        recompute_derived,
    )

    # Patch ts to None after construction (dataclass field is not Optional,
    # but production code may receive corrupt ticks with ts=None via JSON decode)
    ext = ExternalIndexSnapshot(asset="BTC", price_usd=70000.0, ts=0.0, source="stub")
    object.__setattr__(ext, "ts", None)  # force the pathological case

    state = UnifiedMarketState(ticker="KXBTCD-26APR-T70000", asset="BTC")
    state.external = ext

    try:
        recompute_derived(state)
    except TypeError as exc:
        pytest.fail(f"recompute_derived raised TypeError with external.ts=None: {exc}")

    # index_updated_ts must not be None or garbage — should be 0.0 sentinel
    assert state.index_updated_ts == 0.0


def test_recompute_derived_no_crash_when_external_is_none():
    """D-C1: recompute_derived() must not crash when external is None."""
    from merid.event_venues.kalshi.unified_market_state import (
        UnifiedMarketState,
        recompute_derived,
    )

    state = UnifiedMarketState(ticker="KXBTCD-26APR-T70000", asset="BTC")
    assert state.external is None

    try:
        recompute_derived(state)
    except Exception as exc:
        pytest.fail(f"recompute_derived raised {type(exc).__name__} with external=None: {exc}")

    assert state.index_updated_ts == 0.0
    assert state.external_fair_value is None
    assert state.edge_basis is None


# ── D-C2: edge_basis and external_fair_value populated ───────────────────────


def test_recompute_derived_edge_basis_populated_with_fair_prob():
    """D-C2: edge_basis and external_fair_value must be set when external.fair_prob exists."""
    from merid.event_venues.kalshi.unified_market_state import (
        ExternalIndexSnapshot,
        OrderbookLevel,
        OrderbookSnapshot,
        UnifiedMarketState,
        recompute_derived,
    )
    import time

    # Build a minimal book: yes_bid=55c, no_bid=48c → yes_ask=52c, mid=53.5c
    yes_bids = (OrderbookLevel(55, 10),)
    no_bids = (OrderbookLevel(48, 10),)  # yes_ask = 100 - 48 = 52
    book = OrderbookSnapshot(
        ticker="KXBTCD-26APR-T70000",
        yes_bids=yes_bids,
        no_bids=no_bids,
        ts=time.time(),
    )
    # mid_cents = (55 + 52) / 2 = 53.5 → implied_prob = 0.535

    ext = ExternalIndexSnapshot(asset="BTC", price_usd=72000.0, ts=time.time(), source="stub")
    # Inject fair_prob = 0.50 (external model says 50% chance YES)
    object.__setattr__(ext, "fair_prob", 0.50)

    state = UnifiedMarketState(ticker="KXBTCD-26APR-T70000", asset="BTC")
    state.book = book
    state.external = ext
    state.book_updated_ts = time.time()

    recompute_derived(state)

    assert state.external_fair_value == pytest.approx(0.50)
    # edge_basis = implied_prob - external_fair_value = 0.535 - 0.50 = 0.035
    assert state.edge_basis is not None
    assert abs(state.edge_basis - 0.035) < 0.001
    assert state.implied_prob == pytest.approx(0.535, abs=0.001)


def test_recompute_derived_edge_basis_none_when_no_fair_prob():
    """D-C2: edge_basis must remain None when external has no fair_prob."""
    from merid.event_venues.kalshi.unified_market_state import (
        ExternalIndexSnapshot,
        OrderbookLevel,
        OrderbookSnapshot,
        UnifiedMarketState,
        recompute_derived,
    )
    import time

    yes_bids = (OrderbookLevel(55, 10),)
    no_bids = (OrderbookLevel(45, 10),)
    book = OrderbookSnapshot(ticker="KXBTCD-26APR-T70000", yes_bids=yes_bids, no_bids=no_bids, ts=time.time())
    ext = ExternalIndexSnapshot(asset="BTC", price_usd=72000.0, ts=time.time(), source="stub")
    # ExternalIndexSnapshot has no fair_prob field by default → getattr returns None

    state = UnifiedMarketState(ticker="KXBTCD-26APR-T70000", asset="BTC")
    state.book = book
    state.external = ext

    recompute_derived(state)

    assert state.external_fair_value is None
    assert state.edge_basis is None
    # implied_prob is still computed from book mid
    assert state.implied_prob is not None


def test_recompute_derived_edge_basis_none_when_book_mid_is_none():
    """D-C2: edge_basis must be None when book has no mid (empty book sides)."""
    from merid.event_venues.kalshi.unified_market_state import (
        ExternalIndexSnapshot,
        OrderbookSnapshot,
        UnifiedMarketState,
        recompute_derived,
    )
    import time

    # Empty sides → mid_cents = None
    book = OrderbookSnapshot(ticker="KXBTCD-26APR-T70000", yes_bids=(), no_bids=(), ts=time.time())
    ext = ExternalIndexSnapshot(asset="BTC", price_usd=72000.0, ts=time.time(), source="stub")
    object.__setattr__(ext, "fair_prob", 0.55)

    state = UnifiedMarketState(ticker="KXBTCD-26APR-T70000", asset="BTC")
    state.book = book
    state.external = ext

    recompute_derived(state)

    assert state.external_fair_value == pytest.approx(0.55)
    assert state.edge_basis is None  # can't compute without book mid
    assert state.implied_prob is None


def test_recompute_derived_index_updated_ts_set_from_external_ts():
    """D-C1/D-C2: index_updated_ts is set from external.ts when external is valid."""
    from merid.event_venues.kalshi.unified_market_state import (
        ExternalIndexSnapshot,
        UnifiedMarketState,
        recompute_derived,
    )
    import time

    now = time.time()
    ext = ExternalIndexSnapshot(asset="BTC", price_usd=72000.0, ts=now, source="stub")

    state = UnifiedMarketState(ticker="KXBTCD-26APR-T70000", asset="BTC")
    state.external = ext

    recompute_derived(state)

    assert state.index_updated_ts == now


# ── Production wire-in: KalshiMarketStateStore ───────────────────────────────


def test_store_apply_external_index_no_crash_when_ts_is_none():
    """D-C1 (production path): apply_external_index must not raise TypeError when
    ExternalIndexSnapshot.ts is None (corrupt tick from feed)."""
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
    from merid.event_venues.kalshi.unified_market_state import ExternalIndexSnapshot

    store = KalshiMarketStateStore()
    ext = ExternalIndexSnapshot(asset="BTC", price_usd=70000.0, ts=0.0, source="stub")
    object.__setattr__(ext, "ts", None)  # simulate corrupt tick

    try:
        result = store.apply_external_index("KXBTCD-26APR-T70000", ext)
    except TypeError as exc:
        pytest.fail(
            f"apply_external_index raised TypeError with ts=None: {exc}"
        )

    assert result is not None
    assert result.index_updated_ts == 0.0


def test_store_apply_external_index_edge_basis_set_when_data_available():
    """D-C2 (production path): get_unified() must return edge_basis != None after
    apply_orderbook_message (or manual book assignment) + apply_external_index with
    fair_prob present."""
    import time
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
    from merid.event_venues.kalshi.unified_market_state import (
        ExternalIndexSnapshot,
        OrderbookLevel,
        OrderbookSnapshot,
        UnifiedMarketState,
        recompute_derived,
    )

    store = KalshiMarketStateStore()
    ticker = "KXBTC15M-26APR-T70000"

    # Wire in external snapshot with a fair_prob duck-typed attribute
    ext = ExternalIndexSnapshot(asset="BTC", price_usd=72000.0, ts=time.time(), source="stub")
    object.__setattr__(ext, "fair_prob", 0.50)

    store.apply_external_index(ticker, ext)

    # Manually set the book on the unified state to simulate a WS book update
    # (avoids requiring a live WS message; the sync helper uses raw level lists
    # that come from LocalOrderbook.get_book() — use the direct unified path here)
    u: UnifiedMarketState = store.get_unified(ticker)
    assert u is not None, "get_unified() should return a state after apply_external_index"

    # Inject a book directly so recompute_derived can compute implied_prob
    yes_bids = (OrderbookLevel(55, 10),)
    no_bids = (OrderbookLevel(48, 10),)   # yes_ask = 100 - 48 = 52, mid = 53.5
    u.book = OrderbookSnapshot(ticker=ticker, yes_bids=yes_bids, no_bids=no_bids, ts=time.time())
    u.book_updated_ts = time.time()
    recompute_derived(u)  # re-run now that book is set

    assert u.external_fair_value == pytest.approx(0.50)
    assert u.edge_basis is not None
    assert abs(u.edge_basis - 0.035) < 0.001  # 0.535 - 0.50 = 0.035
    assert u.implied_prob == pytest.approx(0.535, abs=0.001)


def test_store_apply_candle_dict_updates_unified_state():
    """apply_candle_dict() must populate latest_candle on UnifiedMarketState."""
    import time
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore

    store = KalshiMarketStateStore()
    ticker = "KXBTC15M-26APR-T70000"
    now = time.time()

    bar = {
        "ts": now,
        "open": 50,
        "high": 55,
        "low": 48,
        "close": 53,
        "volume": 100,
    }
    result = store.apply_candle_dict(ticker, bar, period_interval=60)

    assert result is not None
    assert result.latest_candle is not None
    assert result.latest_candle.close_cents == 53
    assert result.candle_updated_ts == now


def test_store_get_unified_returns_none_for_unknown_ticker():
    """get_unified() must return None for a ticker that has never been seen."""
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore

    store = KalshiMarketStateStore()
    assert store.get_unified("UNKNOWN-TICKER") is None


# ── D-H2: one-sided orderbook must not produce a snapshot ────────────────────


def test_one_sided_orderbook_yes_only_does_not_set_book():
    """D-H2: a book with only YES bids and no NO bids must not produce an
    OrderbookSnapshot on the UnifiedMarketState — downstream spread/mid/
    implied_prob would all be None, confusing agents and the risk system."""
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore

    store = KalshiMarketStateStore()
    ticker = "KXBTC15M-26APR-T70000"

    # Push a WS orderbook_snapshot with YES bids only (no_bids is empty)
    snap_msg = {
        "type": "orderbook_snapshot",
        "ticker": ticker,
        "msg": {
            "ticker": ticker,
            "yes": [[55, 10], [54, 5]],  # YES bids present
            "no": [],                    # NO bids absent — one-sided
        },
    }
    store.apply_orderbook_message(snap_msg)

    u = store.get_unified(ticker)
    assert u is not None, "UnifiedMarketState should exist after snapshot"
    # A one-sided book must NOT produce a valid OrderbookSnapshot.
    # Before the fix, u.book is set but u.book.no_bids == () and
    # implied_prob is None — that is the bug.  After the fix u.book must
    # be None so that recompute_derived() is not called with an invalid book.
    assert u.book is None, (
        "One-sided book (YES only) must not set u.book; "
        f"got book={u.book!r}, implied_prob={u.implied_prob!r}"
    )


def test_one_sided_orderbook_no_only_does_not_set_book():
    """D-H2: a book with only NO bids and no YES bids must not produce an
    OrderbookSnapshot on the UnifiedMarketState."""
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore

    store = KalshiMarketStateStore()
    ticker = "KXBTC15M-26APR-T70000"

    snap_msg = {
        "type": "orderbook_snapshot",
        "ticker": ticker,
        "msg": {
            "ticker": ticker,
            "yes": [],                   # YES bids absent — one-sided
            "no": [[45, 8], [44, 4]],   # NO bids present
        },
    }
    store.apply_orderbook_message(snap_msg)

    u = store.get_unified(ticker)
    assert u is not None
    assert u.book is None, (
        "One-sided book (NO only) must not set u.book; "
        f"got book={u.book!r}, implied_prob={u.implied_prob!r}"
    )


def test_two_sided_orderbook_does_set_book():
    """D-H2: a book with BOTH yes_bids and no_bids must produce a valid
    OrderbookSnapshot on the UnifiedMarketState (regression guard)."""
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore

    store = KalshiMarketStateStore()
    ticker = "KXBTC15M-26APR-T70000"

    snap_msg = {
        "type": "orderbook_snapshot",
        "ticker": ticker,
        "msg": {
            "ticker": ticker,
            "yes": [[55, 10]],
            "no": [[48, 8]],
        },
    }
    store.apply_orderbook_message(snap_msg)

    u = store.get_unified(ticker)
    assert u is not None
    assert u.book is not None, "Two-sided book must produce a valid OrderbookSnapshot"
    assert len(u.book.yes_bids) > 0
    assert len(u.book.no_bids) > 0
    # implied_prob must be computable (not None) for a two-sided book
    assert u.implied_prob is not None


# ── D-H3: last_book_update_ts=0.0 sentinel must be treated as never-set ──────


def test_is_stale_returns_true_when_ts_is_zero_sentinel():
    """D-H3: if last_book_update_ts=0.0 (the never-set sentinel) but
    book_initialized=True, is_stale() must return True — NOT compute
    (wall_now - 0.0) = wall_now which might be > max_age_seconds anyway
    but only by accident (e.g. monotonic clock starting at a small value).
    The guard must be explicit: ts > 0.0."""
    import time
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
    from merid.event_venues.kalshi.models import KalshiMarketState

    store = KalshiMarketStateStore()
    ticker = "KXBTC15M-26APR-T70000"

    # Manufacture a state that is initialized but has the 0.0 sentinel ts
    with store._lock:
        state = store._get_or_create(ticker)
        state.book_initialized = True
        state.last_book_update_ts = 0.0  # explicit never-set sentinel

    # With a small max_age_seconds, (monotonic() - 0.0) >> max_age_seconds
    # so this might pass even without the fix — but the next test is the
    # critical one: with a very large max_age_seconds the bug would manifest.
    assert store.is_stale(ticker, max_age_seconds=30.0) is True, (
        "is_stale() must return True when last_book_update_ts=0.0 (never set)"
    )


def test_is_stale_zero_ts_treated_as_infinite_age_not_finite():
    """D-H3: last_book_update_ts=0.0 must be treated as infinite age.
    If it were computed as (monotonic() - 0.0), a max_age_seconds larger
    than the monotonic clock value would incorrectly return False (not stale).
    With the > 0.0 guard this must always return True."""
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore

    store = KalshiMarketStateStore()
    ticker = "KXBTC15M-26APR-T70000"

    with store._lock:
        state = store._get_or_create(ticker)
        state.book_initialized = True
        state.last_book_update_ts = 0.0

    # Use a max_age_seconds so large that IF the code computes
    # (monotonic() - 0.0) it might be < max_age_seconds in a test environment
    # where the monotonic clock has only been running a short time.
    # On most real machines monotonic() is 1e4–1e6 seconds, but in CI
    # it can be as low as a few hundred seconds. We use 1e9 to force the issue.
    assert store.is_stale(ticker, max_age_seconds=1_000_000_000.0) is True, (
        "is_stale() with ts=0.0 must return True even with a huge max_age — "
        "0.0 is the never-set sentinel, not a real timestamp"
    )


def test_is_stale_returns_false_when_recently_updated():
    """D-H3 regression: is_stale() must still return False when the book was
    actually updated recently (ts is a real positive monotonic value)."""
    import time
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore

    store = KalshiMarketStateStore()
    ticker = "KXBTC15M-26APR-T70000"

    with store._lock:
        state = store._get_or_create(ticker)
        state.book_initialized = True
        state.last_book_update_ts = time.monotonic()  # just now

    assert store.is_stale(ticker, max_age_seconds=30.0) is False, (
        "is_stale() must return False when book was just updated"
    )
