"""
P0 live-execution scenario tests for the Kalshi deterministic simulator.

These tests exercise ``DeterministicKalshiClient`` against the core behaviours
required by live execution and reconciliation paths:

- IOC full / partial / zero-fill and exposure release
- GTC/GTT maker placement, cancellation and expiry
- Reduce-only exit under 10c with IOC/FOK enforcement
- Timeout-after-submit + client_order_id recovery
- Restart state (open, partial, filled, expired market, settled positions)
- Duplicate / out-of-order fill replay
- event_positions vs market_positions split
- Historical settlement fetch
- Category-cap calculation excludes canceled and terminal IOC no-fill orders
- Same-ticker replacement with confirmed cancel before new risk reservation

No network I/O is used; time is explicit and order books are controlled by tests.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pytest

from merid.event_venues.base import VenueOrder, VenuePosition
from merid.event_venues.kalshi.client import get_kalshi_client
from merid.resilience.result import OperationResult

from tests.event_venues.kalshi.deterministic_kalshi_client import (
    DeterministicKalshiClient,
)

TICKER = "KXBTC15M-TEST-50000"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client() -> DeterministicKalshiClient:
    """Fresh, deterministic simulator."""
    c = DeterministicKalshiClient()
    c.set_time(1_700_000_000)
    c.set_balance(Decimal("10000"), locked=Decimal("0"))
    return c


# ---------------------------------------------------------------------------
# Order builders
# ---------------------------------------------------------------------------

def _order(
    ticker: str = TICKER,
    side: str = "buy",
    outcome: str = "yes",
    size: int = 1,
    price: Optional[int] = None,
    tif: str = "GTC",
    client_order_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    post_only: bool = False,
    reduce_only: bool = False,
    expiration_ts: Optional[int] = None,
    order_type: str = "limit",
) -> VenueOrder:
    """Build a ``VenueOrder`` with price in dollars (price==None => market)."""
    price_d = None if price is None else Decimal(price) / Decimal(100)
    return VenueOrder(
        market_id=ticker,
        side=side,
        size=Decimal(size),
        price=price_d,
        order_type=order_type,
        outcome_id=outcome,
        client_order_id=client_order_id,
        time_in_force=tif,
        expiration_ts=expiration_ts,
        post_only=post_only,
        reduce_only=reduce_only,
        idempotency_key=idempotency_key,
    )


# ---------------------------------------------------------------------------
# 1. IOC fills (full, partial, zero) and exposure release
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ioc_full_fill(client: DeterministicKalshiClient) -> None:
    client.set_orderbook(TICKER, best_bid_cents=40, best_ask_cents=55,
                         bid_size=Decimal("10"), ask_size=Decimal("5"))

    order = _order(side="buy", outcome="yes", size=5, price=60, tif="IOC",
                   client_order_id="ioc-full")
    res = await client.place_order_result(order)

    assert res.success, res.error
    placed = res.data
    assert placed is not None
    assert placed.status == "filled"
    assert placed.filled_size == Decimal("5")
    assert placed.remaining_size == Decimal("0")

    assert len(client._fills) == 1
    assert client._fills[0]["count"] == 5

    # Position and balance updated at the resting-ask price.
    pos = await client.get_positions_result()
    assert pos.data[0].size == Decimal("5")
    assert pos.data[0].outcome_id == "yes"
    assert client._balance_usd == Decimal("10000") - (Decimal("5") * Decimal("0.55"))

    # IOC is not an open order.
    open_orders = await client.get_open_orders_result()
    assert open_orders.data == []


@pytest.mark.asyncio
async def test_ioc_partial_fill(client: DeterministicKalshiClient) -> None:
    client.set_orderbook(TICKER, best_bid_cents=40, best_ask_cents=55,
                         bid_size=Decimal("10"), ask_size=Decimal("3"))

    order = _order(side="buy", outcome="yes", size=8, price=60, tif="IOC",
                   client_order_id="ioc-partial")
    res = await client.place_order_result(order)

    assert res.success
    placed = res.data
    assert placed is not None
    assert placed.status == "partially_filled"
    assert placed.filled_size == Decimal("3")
    assert placed.remaining_size == Decimal("0")  # IOC closed

    # Partially filled IOC is not open after execution.
    open_orders = await client.get_open_orders_result()
    assert open_orders.data == []


@pytest.mark.asyncio
async def test_ioc_zero_fill_releases_exposure(client: DeterministicKalshiClient) -> None:
    client.set_orderbook(TICKER, best_bid_cents=40, best_ask_cents=55,
                         bid_size=Decimal("10"), ask_size=Decimal("10"))

    # Buy limit at 50c does not cross the 55c ask.
    order = _order(side="buy", outcome="yes", size=5, price=50, tif="IOC",
                   client_order_id="ioc-zero")
    res = await client.place_order_result(order)

    assert res.success
    placed = res.data
    assert placed is not None
    assert placed.status == "unfilled"
    assert placed.filled_size == Decimal("0")
    assert placed.remaining_size == Decimal("0")

    # No live exposure should remain on the venue.
    open_orders = await client.get_open_orders_result()
    assert open_orders.data == []
    assert client._fills == []
    assert client._balance_usd == Decimal("10000")


# ---------------------------------------------------------------------------
# 2. GTC/GTT maker placement, cancellation and expiry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gtc_maker_cancel_and_gtt_expiry(client: DeterministicKalshiClient) -> None:
    client.set_orderbook(TICKER, best_bid_cents=40, best_ask_cents=60,
                         bid_size=Decimal("10"), ask_size=Decimal("10"))
    now = client.get_time()

    # GTC resting order (no cross: 50 < 60 ask).
    gtc = _order(side="buy", outcome="yes", size=5, price=50, tif="GTC",
                 client_order_id="gtc-resting")
    res = await client.place_order_result(gtc)
    placed = res.data
    assert placed is not None
    assert placed.status == "resting"
    assert placed.raw_data["time_in_force"] == "GTC"
    assert placed.raw_data["client_order_id"] == "gtc-resting"
    assert await client.get_open_orders_result() and len(
        (await client.get_open_orders_result()).data
    ) == 1

    # Cancel and confirm.
    cancel_res = await client.cancel_order_result(placed.order_id)
    assert cancel_res.success
    assert cancel_res.data is True

    order_after = await client.get_order_result(placed.order_id)
    assert order_after.data is not None
    assert order_after.data.status == "canceled"
    assert (await client.get_open_orders_result()).data == []

    # GTT order placed with a future expiration.
    gtt = _order(side="buy", outcome="yes", size=3, price=45, tif="GTT",
                 client_order_id="gtt-resting", expiration_ts=now + 100)
    gtt_res = await client.place_order_result(gtt)
    assert gtt_res.data is not None
    assert gtt_res.data.status == "resting"
    assert gtt_res.data.raw_data["time_in_force"] == "GTT"
    assert gtt_res.data.raw_data.get("expiration_ts") is None  # stored on entry

    # Before expiry it is open.
    client.set_time(now + 50)
    assert (await client.get_open_orders_result()).data

    # After expiry the status becomes expired and it is not open.
    client.set_time(now + 200)
    expired = await client.get_order_result(gtt_res.data.order_id)
    assert expired.data is not None
    assert expired.data.status == "expired"
    assert (await client.get_open_orders_result()).data == []


# ---------------------------------------------------------------------------
# 3. Reduce-only exit under 10c
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reduce_only_exit_under_ten_ioc_and_fok(client: DeterministicKalshiClient) -> None:
    # Book is deep below the 10c floor: best bid 5c.
    client.set_orderbook(TICKER, best_bid_cents=5, best_ask_cents=95,
                         bid_size=Decimal("20"), ask_size=Decimal("20"))
    client.set_initial_position(TICKER, "yes", 5, avg_price_cents=50)

    # Reduce-only SELL YES at 5c (user price) => YES-space 5c.  IOC.
    ioc = _order(side="sell", outcome="yes", size=5, price=5, tif="IOC",
                 client_order_id="reduce-ioc", reduce_only=True)
    res = await client.place_order_result(ioc)
    assert res.success, res.error
    assert res.data is not None
    assert res.data.status == "filled"
    assert res.data.filled_size == Decimal("5")

    # Position closed; balance receives 5 * $0.05.
    assert client._position_yes.get(TICKER) == Decimal("0")
    assert client._balance_usd == Decimal("10000") + (Decimal("5") * Decimal("0.05"))

    # Re-establish a long YES position for the FOK case.
    client.set_initial_position(TICKER, "yes", 5, avg_price_cents=50)
    fok = _order(side="sell", outcome="yes", size=5, price=5, tif="FOK",
                 client_order_id="reduce-fok", reduce_only=True)
    res2 = await client.place_order_result(fok)
    assert res2.success
    assert res2.data is not None
    assert res2.data.status == "filled"
    assert res2.data.filled_size == Decimal("5")

    # A non-reduce order at the same price should NOT fill below 10c.
    client.set_initial_position(TICKER, "yes", 5, avg_price_cents=50)
    bad_ioc = _order(side="sell", outcome="yes", size=5, price=5, tif="IOC",
                     client_order_id="non-reduce", reduce_only=False)
    res3 = await client.place_order_result(bad_ioc)
    assert res3.success
    assert res3.data is not None
    assert res3.data.status == "unfilled"

    # A reduce-only order without an offsetting position is rejected.
    client._position_yes.pop(TICKER, None)
    client._position_cost.pop(TICKER, None)
    rej = _order(side="sell", outcome="yes", size=5, price=5, tif="IOC",
                 client_order_id="reduce-no-pos", reduce_only=True)
    res4 = await client.place_order_result(rej)
    assert not res4.success


# ---------------------------------------------------------------------------
# 4. Timeout after submit + client_order_id recovery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_timeout_after_submit_then_idempotent_recovery(client: DeterministicKalshiClient) -> None:
    client.set_orderbook(TICKER, best_bid_cents=40, best_ask_cents=60,
                         bid_size=Decimal("10"), ask_size=Decimal("10"))
    client.set_timeout_after_submit("once")

    order = _order(side="buy", outcome="yes", size=1, price=50, tif="GTC",
                   client_order_id="timeout-co")
    res = await client.place_order_result(order)

    # First call records the order but returns a timeout.
    assert not res.success
    assert isinstance(res.error, asyncio.TimeoutError)

    # The order must still be retrievable by client_order_id (it has already
    # been matched / recorded by the venue even though the HTTP response timed out).
    lookup = await client.get_order_by_client_id_result("timeout-co")
    assert lookup.success
    assert lookup.data is not None
    assert lookup.data.client_order_id == "timeout-co"
    assert lookup.data.status == "resting"  # price 50c does not cross ask 60c

    # A retry with the same client_order_id is idempotent and succeeds.
    retry = await client.place_order_result(order)
    assert retry.success
    assert retry.data is not None
    assert retry.data.order_id == lookup.data.order_id
    assert retry.data.status == "resting"


# ---------------------------------------------------------------------------
# 5. Restart state: open, partial, filled, expired market, settled position
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_restart_state(client: DeterministicKalshiClient) -> None:
    open_ticker = TICKER
    expired_ticker = "KXBTC15M-TEST-EXPIRED"

    client.set_orderbook(open_ticker, best_bid_cents=40, best_ask_cents=55,
                         bid_size=Decimal("10"), ask_size=Decimal("1"))
    client.set_orderbook(expired_ticker, best_bid_cents=40, best_ask_cents=55,
                         bid_size=Decimal("10"), ask_size=Decimal("1"))

    # Open GTC order.
    gtc = _order(ticker=open_ticker, side="buy", outcome="yes", size=2,
                 price=50, tif="GTC", client_order_id="restart-open")
    await client.place_order_result(gtc)

    # Partial fill (only 1 contract available at ask).
    partial = _order(ticker=open_ticker, side="buy", outcome="yes", size=5,
                     price=60, tif="GTC", client_order_id="restart-partial")
    partial_res = await client.place_order_result(partial)
    assert partial_res.data is not None
    assert partial_res.data.status == "partially_filled"
    assert partial_res.data.filled_size == Decimal("1")

    # Replenish the book so the next order can fully fill.
    client.set_orderbook(open_ticker, best_bid_cents=40, best_ask_cents=55,
                         bid_size=Decimal("10"), ask_size=Decimal("10"))

    # Fully filled order.
    filled = _order(ticker=open_ticker, side="buy", outcome="yes", size=3,
                    price=60, tif="IOC", client_order_id="restart-filled")
    filled_res = await client.place_order_result(filled)
    assert filled_res.data is not None
    assert filled_res.data.status == "filled"
    assert filled_res.data.filled_size == Decimal("3")

    # Expire one market; any resting orders there should become expired.
    client.set_market_expired(expired_ticker)
    expired_market = await client.get_market_result(expired_ticker)
    assert expired_market.data is not None
    assert expired_market.data.resolved is True
    assert expired_market.data.active is False

    # Settled / historical position not in live endpoints.
    client.set_historical_positions([
        VenuePosition(
            market_id=expired_ticker,
            outcome_id="yes",
            size=Decimal("10"),
            average_entry_price=Decimal("0.50"),
            venue="kalshi",
        ),
    ])

    # Live get_positions should not include the settled position.
    live = await client.get_positions_result()
    assert all(p.market_id != expired_ticker for p in live.data)

    # Historical endpoint resolves it.
    hist = await client.get_historical_positions_result()
    assert any(p.market_id == expired_ticker for p in hist.data)

    # Open orders exclude filled/canceled/expired.
    open_orders = await client.get_open_orders_result()
    assert len(open_orders.data) == 2  # gtc + partial
    assert all(o.client_order_id in ("restart-open", "restart-partial") for o in open_orders.data)


# ---------------------------------------------------------------------------
# 6. Duplicate / out-of-order fill replay
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_duplicate_fill_replay(client: DeterministicKalshiClient) -> None:
    fill = {
        "trade_id": "trade-dup",
        "order_id": "some-order",
        "market_ticker": TICKER,
        "side": "yes",
        "action": "buy",
        "count": 1,
        "yes_price": 50,
        "no_price": 50,
        "created_time": datetime.fromtimestamp(client.get_time(), tz=timezone.utc).isoformat(),
    }

    client.inject_fill(fill)
    client.inject_fill(fill)  # deliberate duplicate

    # get_fills must not deduplicate.
    fills = await client.get_fills()
    assert len(fills.data) == 2
    assert fills.data[0]["trade_id"] == fills.data[1]["trade_id"]

    # Out-of-order: a fill timestamped *before* the order was accepted still appears.
    old_fill = dict(fill)
    old_fill["trade_id"] = "trade-old"
    old_fill["created_time"] = datetime.fromtimestamp(
        client.get_time() - 10_000, tz=timezone.utc
    ).isoformat()
    client.inject_fill(old_fill)

    all_fills = await client.get_fills()
    assert len(all_fills.data) == 3

    # since_ts filtering still works without deduplication.
    recent = await client.get_fills(since_ts=client.get_time() - 5)
    assert len(recent.data) == 2


# ---------------------------------------------------------------------------
# 7. event_positions populated while market_positions empty
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_event_positions_while_market_positions_empty(client: DeterministicKalshiClient) -> None:
    client.set_live_positions(
        market_positions=[],
        event_positions=[
            {
                "ticker": TICKER,
                "side": "yes",
                "count": 7,
                "avg_price_dollars": Decimal("0.55"),
            },
        ],
    )

    pos = await client.get_positions_result()
    assert len(pos.data) == 1
    assert pos.data[0].market_id == TICKER
    assert pos.data[0].outcome_id == "yes"
    assert pos.data[0].size == Decimal("7")
    assert pos.data[0].average_entry_price == Decimal("0.55")


# ---------------------------------------------------------------------------
# 8. Historical settlement fetch resolves a position absent from live endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_historical_settlement_fetch(client: DeterministicKalshiClient) -> None:
    client.set_live_positions(market_positions=[], event_positions=[])
    client.set_historical_positions([
        VenuePosition(
            market_id="KXBTC15M-TEST-SETTLED",
            outcome_id="yes",
            size=Decimal("12"),
            average_entry_price=Decimal("0.60"),
            venue="kalshi",
        ),
    ])

    live = await client.get_positions_result()
    assert live.data == []

    hist = await client.get_historical_positions_result()
    assert len(hist.data) == 1
    assert hist.data[0].market_id == "KXBTC15M-TEST-SETTLED"


# ---------------------------------------------------------------------------
# 9. Category-cap calculation excludes canceled and terminal IOC no-fill orders
# ---------------------------------------------------------------------------

@dataclass
class FakeUnifiedRiskManager:
    last_category: Optional[str] = None
    last_exposure: float = 0.0

    def reconcile_category_exposure(self, category: str, confirmed_open_notional_usd: float) -> None:
        self.last_category = category
        self.last_exposure = confirmed_open_notional_usd


@pytest.mark.asyncio
async def test_category_cap_excludes_canceled_and_terminal_ioc(
    client: DeterministicKalshiClient, monkeypatch: Any
) -> None:
    client.set_orderbook(TICKER, best_bid_cents=40, best_ask_cents=60,
                         bid_size=Decimal("10"), ask_size=Decimal("10"))
    client.set_time(int(time.time()))  # avoid stale-age cancellation in reconcile

    # Live GTC resting order that should count toward the category cap.
    gtc = _order(side="buy", outcome="yes", size=5, price=50, tif="GTC",
                 client_order_id="cap-gtc")
    gtc_res = await client.place_order_result(gtc)
    assert gtc_res.data is not None
    assert gtc_res.data.status == "resting"

    # GTC order then canceled; should be excluded.
    canc = _order(side="buy", outcome="yes", size=3, price=50, tif="GTC",
                  client_order_id="cap-canceled")
    canc_res = await client.place_order_result(canc)
    assert canc_res.data is not None
    await client.cancel_order_result(canc_res.data.order_id)

    # Terminal IOC no-fill; should be excluded.
    ioc = _order(side="buy", outcome="yes", size=2, price=50, tif="IOC",
                 client_order_id="cap-ioc")
    ioc_res = await client.place_order_result(ioc)
    assert ioc_res.data is not None
    assert ioc_res.data.status == "unfilled"

    # Monkey-patch the client and unified risk manager.
    monkeypatch.setattr(
        "merid.event_venues.kalshi.client.get_kalshi_client", lambda: client
    )
    fake_urm = FakeUnifiedRiskManager()
    monkeypatch.setattr(
        "merid.risk.unified_risk_manager.get_unified_risk_manager", lambda: fake_urm
    )

    from merid.event_venues.kalshi.kalshi_risk import (
        reconcile_unified_risk_with_venue,
    )

    result = await reconcile_unified_risk_with_venue(
        max_order_age_seconds=1_000_000_000, category="crypto"
    )

    # Only the live GTC notional should be confirmed:
    # 5 contracts * $0.50 limit price = $2.50.
    assert result["confirmed_open_notional_usd"] == pytest.approx(2.5)
    assert fake_urm.last_exposure == pytest.approx(2.5)
    assert fake_urm.last_category == "crypto"

    # Canceled and IOC no-fill should not appear in live open orders.
    open_ids = [o.client_order_id for o in (await client.get_open_orders_result()).data]
    assert open_ids == ["cap-gtc"]


# ---------------------------------------------------------------------------
# 10. Same-ticker order replacement: cancel confirmed before new reservation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_same_ticker_order_replacement_after_confirmed_cancel(
    client: DeterministicKalshiClient
) -> None:
    client.set_orderbook(TICKER, best_bid_cents=40, best_ask_cents=60,
                         bid_size=Decimal("10"), ask_size=Decimal("10"))

    old = _order(side="buy", outcome="yes", size=2, price=45, tif="GTC",
                 client_order_id="old-replace")
    old_res = await client.place_order_result(old)
    assert old_res.data is not None
    old_oid = old_res.data.order_id

    # A simple risk-reservation gate: only allow a new order once the old one
    # is confirmed canceled.  While the old order is live, the new reservation
    # must not become active.
    reservation_active = False

    async def attempt_replace() -> OperationResult[Optional[Any]]:
        nonlocal reservation_active
        cancel_res = await client.cancel_order_result(old_oid)
        if not cancel_res.success:
            return OperationResult.fail(ValueError("cancel failed"))
        confirmed = await client.get_order_result(old_oid)
        if confirmed.data is None or confirmed.data.status != "canceled":
            return OperationResult.fail(ValueError("cancel not confirmed"))
        reservation_active = True
        new = _order(side="buy", outcome="yes", size=2, price=46, tif="GTC",
                     client_order_id="new-replace")
        return await client.place_order_result(new)

    # Before replacement the old order is open.
    assert len((await client.get_open_orders_result()).data) == 1

    replace_res = await attempt_replace()
    assert replace_res.success, replace_res.error
    assert replace_res.data is not None
    assert replace_res.data.status == "resting"
    assert replace_res.data.client_order_id == "new-replace"
    assert reservation_active is True

    # Old order is gone; new order is the only live one.
    open_orders = (await client.get_open_orders_result()).data
    assert len(open_orders) == 1
    assert open_orders[0].client_order_id == "new-replace"
