"""Tests for PM Coinbase ticker subsystem in data/live_price_feed.py.

Covers:
- _fetch_coinbase_ticker: success, HTTP error, missing price, invalid response
- _coinbase_ticker_loop: records tick, backoff on failure, cancellation
- start_pm_coinbase_streaming: staggered startup, idempotent, task creation
- stop_pm_coinbase_streaming: cancels tasks
- get_pm_feed_health_snapshot: status transitions (ok, pm_max_age_exceeded,
  live_price_feed_unhealthy, warming_up), symbol-key alignment, hard gate flag
"""

import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data.live_price_feed import (
    KALSHI_ASSETS,
    KALSHI_COINBASE_PAIRS,
    LIVE_FEED_HEALTH_MAX_AGE_S,
    PM_MAX_SPOT_AGE_S,
    PM_WARMUP_GRACE_S,
    LivePriceFeed,
    PriceData,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_feed() -> LivePriceFeed:
    """Create a LivePriceFeed with network and exchange init suppressed."""
    with (
        patch("data.live_price_feed.get_network_client") as mock_net,
        patch.object(LivePriceFeed, "_initialize_exchanges"),
    ):
        mock_net.return_value = MagicMock()
        feed = LivePriceFeed()
    return feed


def _inject_tick(feed: LivePriceFeed, asset: str, price: float, age_s: float = 0.0) -> None:
    """Simulate a successful tick for *asset* with given price and age."""
    asset_up = asset.upper()
    now_dt = datetime.now(timezone.utc)
    feed.price_cache[asset_up] = PriceData(
        symbol=asset_up,
        price=price,
        bid=price * 0.9998,
        ask=price * 1.0002,
        volume_24h=0.0,
        change_24h_pct=0.0,
        timestamp=now_dt,
        exchange="coinbase_usd",
    )
    feed._pm_last_tick_mono[asset_up] = time.monotonic() - age_s


# ---------------------------------------------------------------------------
# _fetch_coinbase_ticker
# ---------------------------------------------------------------------------


class TestFetchCoinbaseTicker:
    """Unit tests for LivePriceFeed._fetch_coinbase_ticker."""

    @pytest.mark.asyncio
    async def test_success_returns_mid_price(self):
        """Valid best-bid-ask response returns the mid-price."""
        feed = _make_feed()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "pricebooks": [
                {
                    "product_id": "BTC-USD",
                    "bids": [{"price": "69990.00", "size": "0.5"}],
                    "asks": [{"price": "70010.00", "size": "0.5"}],
                }
            ]
        }
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            price = await feed._fetch_coinbase_ticker("BTC")

        assert price == pytest.approx(70000.0)

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        """HTTP 4xx/5xx returns None and logs a warning."""
        feed = _make_feed()
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "rate limited"
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            price = await feed._fetch_coinbase_ticker("ETH")

        assert price is None

    @pytest.mark.asyncio
    async def test_empty_pricebook_returns_none(self):
        """Response with no matching pricebook returns None."""
        feed = _make_feed()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"pricebooks": []}
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            price = await feed._fetch_coinbase_ticker("SOL")

        assert price is None

    @pytest.mark.asyncio
    async def test_network_exception_returns_none(self):
        """Network exception returns None without raising."""
        feed = _make_feed()
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
            mock_client_cls.return_value = mock_client
            price = await feed._fetch_coinbase_ticker("XRP")

        assert price is None

    @pytest.mark.asyncio
    async def test_unknown_asset_returns_none(self):
        """Unknown asset key returns None immediately without making HTTP calls."""
        feed = _make_feed()
        with patch("httpx.AsyncClient") as mock_client_cls:
            price = await feed._fetch_coinbase_ticker("UNKNOWN")

        assert price is None
        mock_client_cls.assert_not_called()


# ---------------------------------------------------------------------------
# _coinbase_ticker_loop
# ---------------------------------------------------------------------------


class TestCoinbaseTickerLoop:
    """Tests for the per-asset ticker loop."""

    @pytest.mark.asyncio
    async def test_successful_tick_records_price_and_resets_failures(self):
        """On success: price_cache updated, tick clock set, failures reset."""
        feed = _make_feed()
        feed._pm_consecutive_failures["BTC"] = 5  # pre-existing failures

        call_count = 0

        async def mock_fetch(asset):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return 70000.0
            raise asyncio.CancelledError()

        feed._fetch_coinbase_ticker = mock_fetch  # type: ignore[method-assign]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            try:
                await asyncio.wait_for(feed._coinbase_ticker_loop("BTC"), timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        assert "BTC" in feed.price_cache
        assert feed.price_cache["BTC"].price == pytest.approx(70000.0)
        assert feed._pm_last_tick_mono["BTC"] is not None
        assert feed._pm_consecutive_failures["BTC"] == 0

    @pytest.mark.asyncio
    async def test_backoff_applied_after_threshold_failures(self):
        """After _CB_BACKOFF_THRESHOLD failures the sleep interval grows."""
        from data.live_price_feed import _CB_BACKOFF_THRESHOLD, _CB_POLL_INTERVAL_S

        feed = _make_feed()
        sleep_calls = []
        fail_count = 0

        async def mock_sleep(s):
            sleep_calls.append(s)
            if len(sleep_calls) >= _CB_BACKOFF_THRESHOLD + 1:
                raise asyncio.CancelledError()

        async def mock_fetch(asset):
            nonlocal fail_count
            fail_count += 1
            return None  # always fail

        feed._fetch_coinbase_ticker = mock_fetch  # type: ignore[method-assign]

        with patch("asyncio.sleep", side_effect=mock_sleep):
            try:
                await feed._coinbase_ticker_loop("SOL")
            except asyncio.CancelledError:
                pass

        # Early sleeps should be normal cadence; later ones should be longer
        assert sleep_calls[0] == pytest.approx(_CB_POLL_INTERVAL_S)
        # At least one backoff sleep should be larger than normal cadence
        assert any(s > _CB_POLL_INTERVAL_S for s in sleep_calls)

    @pytest.mark.asyncio
    async def test_cancellation_exits_cleanly(self):
        """CancelledError causes the loop to exit without raising."""
        feed = _make_feed()

        async def mock_fetch(asset):
            raise asyncio.CancelledError()

        feed._fetch_coinbase_ticker = mock_fetch  # type: ignore[method-assign]

        # Should not raise
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await feed._coinbase_ticker_loop("DOGE")

    @pytest.mark.asyncio
    async def test_startup_delay_respected(self):
        """startup_delay causes an initial sleep before the first fetch."""
        feed = _make_feed()
        sleep_delays = []

        async def mock_sleep(s):
            sleep_delays.append(s)
            if len(sleep_delays) >= 1:
                # Cancel the loop after first sleep (the startup delay)
                # The loop handles CancelledError internally and exits cleanly
                raise asyncio.CancelledError()

        async def mock_fetch(asset):
            return 1.0

        feed._fetch_coinbase_ticker = mock_fetch  # type: ignore[method-assign]

        with patch("asyncio.sleep", side_effect=mock_sleep):
            # The loop catches CancelledError during startup delay and returns
            await feed._coinbase_ticker_loop("ETH", startup_delay=3.0)

        assert sleep_delays[0] == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# start_pm_coinbase_streaming / stop_pm_coinbase_streaming
# ---------------------------------------------------------------------------


class TestPmStreamingLifecycle:
    """Tests for staggered startup and task management."""

    def test_start_creates_task_for_each_asset(self):
        """start_pm_coinbase_streaming spawns one task per Kalshi asset."""
        feed = _make_feed()
        mock_tasks = {}

        def mock_create_task(coro, name=None):
            task = MagicMock()
            task.done.return_value = False
            mock_tasks[name] = task
            coro.close()  # clean up coroutine
            return task

        loop = MagicMock()
        loop.create_task.side_effect = mock_create_task

        with patch("asyncio.get_event_loop", return_value=loop):
            feed.start_pm_coinbase_streaming()

        assert len(mock_tasks) == len(KALSHI_ASSETS)
        for asset in KALSHI_ASSETS:
            assert f"pm_coinbase_ticker_{asset}" in mock_tasks

    def test_start_sets_pm_start_mono(self):
        """start_pm_coinbase_streaming records _pm_start_mono."""
        feed = _make_feed()
        assert feed._pm_start_mono is None

        loop = MagicMock()
        loop.create_task.side_effect = lambda coro, name=None: (coro.close(), MagicMock())[1]

        with patch("asyncio.get_event_loop", return_value=loop):
            feed.start_pm_coinbase_streaming()

        assert feed._pm_start_mono is not None

    def test_start_is_idempotent_for_running_tasks(self):
        """Calling start twice does not create duplicate tasks for live assets."""
        feed = _make_feed()
        created = []

        def mock_create_task(coro, name=None):
            task = MagicMock()
            task.done.return_value = False
            created.append(name)
            coro.close()
            return task

        loop = MagicMock()
        loop.create_task.side_effect = mock_create_task

        with patch("asyncio.get_event_loop", return_value=loop):
            feed.start_pm_coinbase_streaming()
            first_count = len(created)
            # Second call should not create new tasks since all are "running"
            feed.start_pm_coinbase_streaming()

        assert len(created) == first_count  # no new tasks on second call

    def test_stagger_delays_increase_per_asset(self):
        """Each asset should receive an increasing startup_delay."""
        feed = _make_feed()
        delays_seen = []
        tasks_created = []

        async def mock_ticker_loop(asset, startup_delay=0.0):
            delays_seen.append((asset, startup_delay))

        feed._coinbase_ticker_loop = mock_ticker_loop  # type: ignore[method-assign]

        loop = MagicMock()

        def mock_create_task(coro, name=None):
            # Drive the coroutine one step to capture the delay argument
            import inspect
            # We patched _coinbase_ticker_loop so coro is already driven; just record
            task = MagicMock()
            task.done.return_value = False
            tasks_created.append(task)
            # coro is the coroutine of _coinbase_ticker_loop — run it
            asyncio.get_event_loop_policy().get_event_loop().run_until_complete(coro)
            return task

        with patch("asyncio.get_event_loop", return_value=loop):
            # Use a real event loop to drive the coros
            real_loop = asyncio.new_event_loop()
            try:
                real_loop_tasks = []

                def real_create_task(coro, name=None):
                    real_loop_tasks.append(real_loop.run_until_complete(coro))
                    task = MagicMock()
                    task.done.return_value = False
                    return task

                loop.create_task.side_effect = real_create_task
                feed.start_pm_coinbase_streaming()
            finally:
                real_loop.close()

        # All assets should have been started with increasing delays
        delays_only = sorted(d for _, d in delays_seen)
        from data.live_price_feed import _CB_STAGGER_S
        assert len(delays_seen) == len(KALSHI_ASSETS)
        for i, d in enumerate(delays_only):
            assert d == pytest.approx(i * _CB_STAGGER_S)

    def test_stop_cancels_all_tasks(self):
        """stop_pm_coinbase_streaming cancels every running task."""
        feed = _make_feed()
        mock_tasks = {}
        for asset in KALSHI_ASSETS:
            t = MagicMock()
            t.done.return_value = False
            mock_tasks[asset] = t
            feed._pm_ticker_tasks[asset] = t

        feed.stop_pm_coinbase_streaming()

        for asset, task in mock_tasks.items():
            task.cancel.assert_called_once()


# ---------------------------------------------------------------------------
# get_pm_feed_health_snapshot
# ---------------------------------------------------------------------------


class TestGetPmFeedHealthSnapshot:
    """Tests for get_pm_feed_health_snapshot()."""

    def test_all_fresh_ticks_returns_ok(self):
        """All assets with recent ticks → all status=ok, all_ok=True."""
        feed = _make_feed()
        for asset in KALSHI_ASSETS:
            _inject_tick(feed, asset, price=100.0, age_s=5.0)

        snap = feed.get_pm_feed_health_snapshot()

        assert snap["all_ok"] is True
        assert snap["pm_spot_hard_gate_open"] is True
        for asset in KALSHI_ASSETS:
            assert snap["assets"][asset]["status"] == "ok"
            assert snap["assets"][asset]["feed_ok"] is True

    def test_eth_tick_at_50s_passes_pm_gate(self):
        """ETH tick age 50s < PM_MAX_SPOT_AGE_S=90s → status=ok."""
        feed = _make_feed()
        for asset in KALSHI_ASSETS:
            _inject_tick(feed, asset, price=100.0, age_s=5.0)
        # Override ETH with 50s-old tick
        _inject_tick(feed, "ETH", price=3000.0, age_s=50.0)

        snap = feed.get_pm_feed_health_snapshot()

        assert snap["assets"]["ETH"]["status"] == "ok"
        assert snap["assets"]["ETH"]["tick_age_s"] == pytest.approx(50.0, abs=1.0)

    def test_eth_tick_at_77s_fails_pm_gate_but_feed_healthy(self):
        """ETH tick age 77.7s > PM_MAX_SPOT_AGE_S=90? No — 77.7 < 90 → ok.

        But if PM_MAX_SPOT_AGE_S were 60 (old default) it would fail.
        Here we test with a tick just above PM_MAX_SPOT_AGE_S to verify
        pm_max_age_exceeded while feed_ok remains True.
        """
        feed = _make_feed()
        for asset in KALSHI_ASSETS:
            _inject_tick(feed, asset, price=100.0, age_s=5.0)

        # Simulate tick at PM_MAX_SPOT_AGE_S + 5 seconds (stale for PM)
        stale_age = PM_MAX_SPOT_AGE_S + 5.0
        _inject_tick(feed, "ETH", price=3000.0, age_s=stale_age)

        snap = feed.get_pm_feed_health_snapshot()

        eth = snap["assets"]["ETH"]
        assert eth["status"] == "pm_max_age_exceeded", (
            f"Expected pm_max_age_exceeded but got {eth['status']} "
            f"(tick_age={eth['tick_age_s']:.1f}s, threshold={PM_MAX_SPOT_AGE_S}s)"
        )
        assert eth["feed_ok"] is True, "Feed should still be considered alive"
        assert snap["all_ok"] is False

    def test_sol_xrp_doge_never_ticked_unhealthy(self):
        """SOL/XRP/DOGE with no ticks → live_price_feed_unhealthy."""
        feed = _make_feed()
        # Only BTC and ETH have ticks; SOL/XRP/DOGE never ticked
        _inject_tick(feed, "BTC", price=70000.0, age_s=3.0)
        _inject_tick(feed, "ETH", price=3000.0, age_s=3.0)

        snap = feed.get_pm_feed_health_snapshot()

        assert snap["all_ok"] is False
        for asset in ("SOL", "XRP", "DOGE"):
            s = snap["assets"][asset]["status"]
            assert s == "live_price_feed_unhealthy", (
                f"{asset} should be unhealthy but got {s}"
            )
            assert snap["assets"][asset]["feed_ok"] is False
            assert snap["assets"][asset]["tick_age_s"] is None

    def test_tick_beyond_health_max_age_unhealthy(self):
        """Tick older than LIVE_FEED_HEALTH_MAX_AGE_S → live_price_feed_unhealthy."""
        feed = _make_feed()
        for asset in KALSHI_ASSETS:
            _inject_tick(feed, asset, price=100.0, age_s=5.0)

        # Simulate SOL tick that is very old (beyond health max)
        very_old_age = LIVE_FEED_HEALTH_MAX_AGE_S + 30.0
        _inject_tick(feed, "SOL", price=150.0, age_s=very_old_age)

        snap = feed.get_pm_feed_health_snapshot()

        sol = snap["assets"]["SOL"]
        assert sol["status"] == "live_price_feed_unhealthy"
        assert sol["feed_ok"] is False
        assert snap["all_ok"] is False

    def test_warming_up_status_before_first_tick(self):
        """Within warmup grace window, never-ticked asset → warming_up (not unhealthy)."""
        feed = _make_feed()
        # Set start_mono to now (within grace)
        feed._pm_start_mono = time.monotonic()
        # No ticks at all

        snap = feed.get_pm_feed_health_snapshot()

        # All assets are in warmup
        for asset in KALSHI_ASSETS:
            assert snap["assets"][asset]["status"] == "warming_up", (
                f"{asset} should be warming_up but got {snap['assets'][asset]['status']}"
            )

    def test_btc_ok_does_not_affect_sol_unhealthy(self):
        """BTC health should be independent of SOL health."""
        feed = _make_feed()
        _inject_tick(feed, "BTC", price=70000.0, age_s=3.0)
        _inject_tick(feed, "ETH", price=3000.0, age_s=3.0)
        _inject_tick(feed, "XRP", price=0.5, age_s=3.0)
        _inject_tick(feed, "DOGE", price=0.1, age_s=3.0)
        # SOL never ticked

        snap = feed.get_pm_feed_health_snapshot()

        assert snap["assets"]["BTC"]["status"] == "ok"
        assert snap["assets"]["SOL"]["status"] == "live_price_feed_unhealthy"
        assert snap["all_ok"] is False

    def test_symbol_keys_are_bare_uppercase(self):
        """All keys in snapshot['assets'] are bare uppercase Kalshi asset names."""
        feed = _make_feed()
        snap = feed.get_pm_feed_health_snapshot()

        assert set(snap["assets"].keys()) == KALSHI_ASSETS

    def test_coinbase_pairs_all_usd(self):
        """All Coinbase product IDs end in -USD (not -USDT)."""
        for asset, pair in KALSHI_COINBASE_PAIRS.items():
            assert pair.endswith("-USD"), f"{asset}: expected USD pair but got {pair}"

    def test_snapshot_contains_threshold_metadata(self):
        """Snapshot includes the configured thresholds for auditability."""
        feed = _make_feed()
        snap = feed.get_pm_feed_health_snapshot()

        assert "pm_max_spot_age_s" in snap
        assert "live_feed_health_max_age_s" in snap
        assert snap["pm_max_spot_age_s"] == PM_MAX_SPOT_AGE_S
        assert snap["live_feed_health_max_age_s"] == LIVE_FEED_HEALTH_MAX_AGE_S


# ---------------------------------------------------------------------------
# pm_record_tick helper
# ---------------------------------------------------------------------------


class TestPmRecordTick:
    """Tests for _pm_record_tick."""

    def test_record_tick_updates_cache_and_mono(self):
        """_pm_record_tick stores price and resets failure counter."""
        feed = _make_feed()
        feed._pm_consecutive_failures["BTC"] = 7

        feed._pm_record_tick("BTC", 70000.0)

        assert "BTC" in feed.price_cache
        assert feed.price_cache["BTC"].price == 70000.0
        assert feed.price_cache["BTC"].exchange == "coinbase_usd"
        assert feed._pm_last_tick_mono["BTC"] is not None
        assert feed._pm_consecutive_failures["BTC"] == 0
