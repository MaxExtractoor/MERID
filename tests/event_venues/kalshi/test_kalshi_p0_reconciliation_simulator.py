"""
P0 reconciliation tests for the Kalshi deterministic simulator.

These tests exercise ``merid.event_venues.kalshi.kalshi_risk.reconcile_unified_risk_with_venue``
against ``DeterministicKalshiClient`` injected through ``set_kalshi_execution_port``.

No respx, no network calls — all state is in-memory and deterministic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import pytest

from merid.event_venues.base import VenueOrder, VenuePosition
from merid.event_venues.kalshi.kalshi_risk import reconcile_unified_risk_with_venue
from merid.event_venues.kalshi.port import (
    get_kalshi_execution_port,
    reset_kalshi_execution_port_for_testing,
    set_kalshi_execution_port,
)
from tests.event_venues.kalshi.deterministic_kalshi_client import (
    DeterministicKalshiClient,
)

TICKER = "KXBTC15M-TEST-50000"
EXPIRED_TICKER = "KXBTC15M-TEST-EXPIRED"
POSITION_TICKER = "KXBTC15M-TEST-POSITION"


@dataclass
class FakeUnifiedRiskManager:
    last_category: Optional[str] = None
    last_exposure: float = 0.0

    def reconcile_category_exposure(
        self, category: str, confirmed_open_notional_usd: float
    ) -> None:
        self.last_category = category
        self.last_exposure = confirmed_open_notional_usd


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> DeterministicKalshiClient:
    """Fresh deterministic simulator injected as the global KalshiExecutionPort."""
    c = DeterministicKalshiClient()
    c.set_time(int(time.time()))
    c.set_balance(Decimal("10000"), locked=Decimal("0"))
    set_kalshi_execution_port(c)
    yield c
    reset_kalshi_execution_port_for_testing()


@pytest.fixture
def fake_urm(monkeypatch: pytest.MonkeyPatch) -> FakeUnifiedRiskManager:
    """Fake UnifiedRiskManager so reconciliation state can be asserted."""
    fake = FakeUnifiedRiskManager()
    monkeypatch.setattr(
        "merid.risk.unified_risk_manager.get_unified_risk_manager",
        lambda: fake,
    )
    return fake


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
    """Build a ``VenueOrder`` with ``price`` in cents."""
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
# Reconciliation coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_empty_local_cache(
    client: DeterministicKalshiClient,
    fake_urm: FakeUnifiedRiskManager,
) -> None:
    client.set_orderbook(
        TICKER,
        best_bid_cents=40,
        best_ask_cents=60,
        bid_size=Decimal("10"),
        ask_size=Decimal("10"),
    )

    result = await reconcile_unified_risk_with_venue(
        max_order_age_seconds=1_000_000_000, category="crypto"
    )

    assert result["canceled_order_ids"] == []
    assert result["quarantined_order_ids"] == []
    assert result["confirmed_open_notional_usd"] == pytest.approx(0.0)
    assert fake_urm.last_category == "crypto"
    assert fake_urm.last_exposure == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_reconcile_stale_local_position(
    client: DeterministicKalshiClient,
    fake_urm: FakeUnifiedRiskManager,
) -> None:
    """Local URM exposure that the venue no longer confirms must be reset."""
    client.set_orderbook(
        TICKER,
        best_bid_cents=40,
        best_ask_cents=60,
        bid_size=Decimal("10"),
        ask_size=Decimal("10"),
    )
    fake_urm.reconcile_category_exposure("crypto", 123.45)

    result = await reconcile_unified_risk_with_venue(
        max_order_age_seconds=1_000_000_000, category="crypto"
    )

    assert result["confirmed_open_notional_usd"] == pytest.approx(0.0)
    assert fake_urm.last_exposure == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_reconcile_open_exchange_order(
    client: DeterministicKalshiClient,
    fake_urm: FakeUnifiedRiskManager,
) -> None:
    client.set_orderbook(
        TICKER,
        best_bid_cents=40,
        best_ask_cents=60,
        bid_size=Decimal("10"),
        ask_size=Decimal("10"),
    )

    order = _order(
        side="buy",
        outcome="yes",
        size=4,
        price=50,
        tif="GTC",
        client_order_id="reconcile-open",
    )
    res = await client.place_order_result(order)
    assert res.success
    assert res.data is not None
    assert res.data.status == "resting"
    assert res.data.remaining_size == Decimal("4")

    result = await reconcile_unified_risk_with_venue(
        max_order_age_seconds=1_000_000_000, category="crypto"
    )

    # open order notional = remaining_size * price_cents / 100
    # 4 contracts * $0.50 = $2.00
    assert result["confirmed_open_notional_usd"] == pytest.approx(2.0)
    assert fake_urm.last_exposure == pytest.approx(2.0)
    assert result["canceled_order_ids"] == []
    assert result["quarantined_order_ids"] == []


@pytest.mark.asyncio
async def test_reconcile_partial_fill(
    client: DeterministicKalshiClient,
    fake_urm: FakeUnifiedRiskManager,
) -> None:
    client.set_orderbook(
        TICKER,
        best_bid_cents=40,
        best_ask_cents=55,
        bid_size=Decimal("10"),
        ask_size=Decimal("2"),
    )

    order = _order(
        side="buy",
        outcome="yes",
        size=5,
        price=60,
        tif="GTC",
        client_order_id="reconcile-partial",
    )
    res = await client.place_order_result(order)
    assert res.success
    assert res.data is not None
    assert res.data.status == "partially_filled"
    assert res.data.filled_size == Decimal("2")
    assert res.data.remaining_size == Decimal("3")

    result = await reconcile_unified_risk_with_venue(
        max_order_age_seconds=1_000_000_000, category="crypto"
    )

    # open: 3 remaining * $0.60 = $1.80
    # position: 2 filled * $0.55 = $1.10
    assert result["confirmed_open_notional_usd"] == pytest.approx(2.90)
    assert fake_urm.last_exposure == pytest.approx(2.90)


@pytest.mark.asyncio
async def test_reconcile_expired_market_excluded(
    client: DeterministicKalshiClient,
    fake_urm: FakeUnifiedRiskManager,
) -> None:
    client.set_orderbook(
        EXPIRED_TICKER,
        best_bid_cents=40,
        best_ask_cents=60,
        bid_size=Decimal("10"),
        ask_size=Decimal("10"),
    )

    order = _order(
        ticker=EXPIRED_TICKER,
        side="buy",
        outcome="yes",
        size=4,
        price=50,
        tif="GTC",
        client_order_id="reconcile-expired-market",
    )
    res = await client.place_order_result(order)
    assert res.success
    assert res.data is not None
    assert res.data.status == "resting"

    client.set_market_expired(EXPIRED_TICKER)

    result = await reconcile_unified_risk_with_venue(
        max_order_age_seconds=1_000_000_000, category="crypto"
    )

    # The expired market is no longer live, so its resting order is excluded.
    assert result["confirmed_open_notional_usd"] == pytest.approx(0.0)
    assert fake_urm.last_exposure == pytest.approx(0.0)
    assert result["canceled_order_ids"] == []
    assert result["quarantined_order_ids"] == []


@pytest.mark.asyncio
async def test_reconcile_settled_position_historical(
    client: DeterministicKalshiClient,
    fake_urm: FakeUnifiedRiskManager,
) -> None:
    client.set_historical_positions(
        [
            VenuePosition(
                market_id="KXBTC15M-TEST-SETTLED",
                outcome_id="yes",
                size=Decimal("10"),
                average_entry_price=Decimal("0.60"),
                venue="kalshi",
            ),
        ]
    )
    client.set_live_positions(market_positions=[], event_positions=[])

    result = await reconcile_unified_risk_with_venue(
        max_order_age_seconds=1_000_000_000, category="crypto"
    )

    # Historical / settled positions are not live exposure.
    assert result["confirmed_open_notional_usd"] == pytest.approx(0.0)
    assert fake_urm.last_exposure == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_reconcile_restart_state(
    client: DeterministicKalshiClient,
    fake_urm: FakeUnifiedRiskManager,
) -> None:
    client.set_orderbook(
        TICKER,
        best_bid_cents=40,
        best_ask_cents=60,
        bid_size=Decimal("10"),
        ask_size=Decimal("10"),
    )

    # 1. open GTC order
    open_order = _order(
        ticker=TICKER,
        side="buy",
        outcome="yes",
        size=3,
        price=50,
        tif="GTC",
        client_order_id="restart-open",
    )
    open_res = await client.place_order_result(open_order)
    assert open_res.data is not None
    assert open_res.data.status == "resting"

    # 2. partial fill: only 2 contracts available at the ask
    client.set_orderbook(
        TICKER,
        best_bid_cents=40,
        best_ask_cents=55,
        bid_size=Decimal("10"),
        ask_size=Decimal("2"),
    )
    partial = _order(
        ticker=TICKER,
        side="buy",
        outcome="yes",
        size=5,
        price=60,
        tif="GTC",
        client_order_id="restart-partial",
    )
    partial_res = await client.place_order_result(partial)
    assert partial_res.data is not None
    assert partial_res.data.status == "partially_filled"
    assert partial_res.data.filled_size == Decimal("2")
    assert partial_res.data.remaining_size == Decimal("3")

    # 3. fully filled order
    client.set_orderbook(
        TICKER,
        best_bid_cents=40,
        best_ask_cents=55,
        bid_size=Decimal("10"),
        ask_size=Decimal("10"),
    )
    filled = _order(
        ticker=TICKER,
        side="buy",
        outcome="yes",
        size=3,
        price=60,
        tif="GTC",
        client_order_id="restart-filled",
    )
    filled_res = await client.place_order_result(filled)
    assert filled_res.data is not None
    assert filled_res.data.status == "filled"

    # 4. separate live position
    client.set_live_positions(
        market_positions=[
            {
                "ticker": POSITION_TICKER,
                "side": "yes",
                "count": 4,
                "avg_price_dollars": Decimal("0.45"),
            },
        ],
        event_positions=[],
    )

    result = await reconcile_unified_risk_with_venue(
        max_order_age_seconds=1_000_000_000, category="crypto"
    )

    # open: 3 * $0.50 + 3 remaining * $0.60 = $1.50 + $1.80 = $3.30
    # positions: 5 filled * $0.55 + 4 live * $0.45 = $2.75 + $1.80 = $4.55
    # total = $7.85
    assert result["confirmed_open_notional_usd"] == pytest.approx(7.85)
    assert fake_urm.last_exposure == pytest.approx(7.85)

    open_ids = [o.client_order_id for o in (await client.get_open_orders_result()).data]
    assert sorted(open_ids) == ["restart-open", "restart-partial"]


@pytest.mark.asyncio
async def test_reconcile_category_cap_excludes_canceled_and_ioc_unfilled(
    client: DeterministicKalshiClient,
    fake_urm: FakeUnifiedRiskManager,
) -> None:
    client.set_orderbook(
        TICKER,
        best_bid_cents=40,
        best_ask_cents=60,
        bid_size=Decimal("10"),
        ask_size=Decimal("10"),
    )

    # Live GTC resting order that should count.
    gtc = _order(
        side="buy",
        outcome="yes",
        size=5,
        price=50,
        tif="GTC",
        client_order_id="cap-gtc",
    )
    gtc_res = await client.place_order_result(gtc)
    assert gtc_res.data is not None
    assert gtc_res.data.status == "resting"

    # Canceled GTC should be excluded.
    canc = _order(
        side="buy",
        outcome="yes",
        size=3,
        price=50,
        tif="GTC",
        client_order_id="cap-canceled",
    )
    canc_res = await client.place_order_result(canc)
    assert canc_res.data is not None
    await client.cancel_order_result(canc_res.data.order_id)

    # Terminal IOC no-fill should be excluded.
    ioc = _order(
        side="buy",
        outcome="yes",
        size=2,
        price=50,
        tif="IOC",
        client_order_id="cap-ioc",
    )
    ioc_res = await client.place_order_result(ioc)
    assert ioc_res.data is not None
    assert ioc_res.data.status == "unfilled"

    result = await reconcile_unified_risk_with_venue(
        max_order_age_seconds=1_000_000_000, category="crypto"
    )

    # Only the live GTC counts: 5 contracts * $0.50 = $2.50.
    assert result["confirmed_open_notional_usd"] == pytest.approx(2.5)
    assert fake_urm.last_exposure == pytest.approx(2.5)
    assert fake_urm.last_category == "crypto"

    open_ids = [o.client_order_id for o in (await client.get_open_orders_result()).data]
    assert open_ids == ["cap-gtc"]
