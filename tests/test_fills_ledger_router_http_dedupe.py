"""
Regression test for the 2026-09-02 router / HTTP counterparty fill deduplication
incident.

The same Kalshi execution was observed twice: once as a live-router fill in the
user's intended form (BUY_NO / SELL_NO) and once from the HTTP /portfolio/fills
poller in the counterparty form (SELL_YES / BUY_YES).  Both observations must
collapse into a single ledger mutation and a single position.
"""

import os
import pytest
from datetime import datetime, timezone
from decimal import Decimal


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """Provide an isolated in-memory+SQLite ledger for each test."""
    db_path = tmp_path / "kalshi_fills.db"
    monkeypatch.setenv("MERID_FILLS_DB_PATH", str(db_path))
    # Prevent any code from using a default pool against production.
    monkeypatch.setenv("POSTGRES_PASSWORD", "")
    from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger
    return KalshiFillsLedger()


def _record_intent(ledger, side, action, client_order_id, entry_or_exit="entry"):
    from merid.event_venues.kalshi.fills_ledger import OrderIntent
    intent = OrderIntent(
        intent_id=client_order_id,
        client_order_id=client_order_id,
        ticker="KXBTC15M-TEST",
        side=side,
        action=action,
        count=1,
        price_cents=50,
        entry_or_exit=entry_or_exit,
    )
    ledger.record_intent(intent)


def _router_fill(
    order_id: str,
    client_order_id: str,
    *,
    side: str,
    action: str,
    canonical_side: str,
    canonical_action: str,
    yes_delta: int,
    leg_price_cents: int,
    is_exit: bool = False,
    reduce_only: bool = False,
    entry_or_exit: str = "entry",
) -> "KalshiFill":
    """Build a live-router KalshiFill for the same economic execution."""
    from merid.event_venues.kalshi.fills_ledger import KalshiFill
    return KalshiFill(
        fill_id=f"live_router_{order_id}_0",
        order_id=order_id,
        client_order_id=client_order_id,
        market_ticker="KXBTC15M-TEST",
        side=side,
        action=action,
        count_fp=Decimal("1"),
        quantity_cc=100,
        yes_price_dollars=Decimal("0.48"),
        no_price_dollars=Decimal("0.52"),
        fee_cost=Decimal("0.01"),
        canonical_position_side=canonical_side,
        canonical_position_action=canonical_action,
        canonical_leg_price_cents=leg_price_cents,
        canonical_yes_delta_cc=yes_delta,
        canonicalization_state="TRUSTED_LIVE_V1",
        is_exit=is_exit,
        reduce_only=reduce_only,
        entry_or_exit=entry_or_exit,
    )


def _http_counterparty_raw(
    fill_id: str,
    order_id: str,
    client_order_id: str,
    *,
    side: str,
    action: str,
    outcome_side: str,
    book_side: str,
) -> dict:
    """Build an HTTP /portfolio/fills raw payload in the counterparty form."""
    return {
        "fill_id": fill_id,
        "order_id": order_id,
        "client_order_id": client_order_id,
        "market_ticker": "KXBTC15M-TEST",
        "side": side,
        "action": action,
        "outcome_side": outcome_side,
        "book_side": book_side,
        "yes_price_dollars": "0.48",
        "no_price_dollars": "0.52",
        "count_fp": "1",
        "fee_cost": "0.01",
        "created_time": datetime.now(timezone.utc).isoformat(),
    }


@pytest.mark.asyncio
async def test_http_counterparty_buy_yes_promotes_router_buy_no(ledger):
    """BUY_NO via router, then SELL_YES via HTTP for the same execution."""
    coid = "coid-buy-no-entry"
    order_id = "order-router-http-1"
    _record_intent(ledger, side="BUY_NO", action="buy", client_order_id=coid, entry_or_exit="entry")

    # 1. Live-router fill in the user's form: BUY_NO at NO=52 (YES=48).
    router_fill = _router_fill(
        order_id,
        coid,
        side="no",
        action="buy",
        canonical_side="no",
        canonical_action="buy",
        yes_delta=-100,
        leg_price_cents=52,
    )
    ledger.on_fill(router_fill)

    assert len(ledger._fills) == 1
    assert len(ledger._open_positions) == 1
    key = "KXBTC15M-TEST:no"
    assert key in ledger._open_positions
    assert ledger._open_positions[key]["total_contracts"] == 1

    # 2. HTTP /portfolio/fills returns the counterparty form: SELL_YES at YES=48.
    http_raw = _http_counterparty_raw(
        "http-fill-1",
        order_id,
        coid,
        side="yes",
        action="sell",
        outcome_side="yes",
        book_side="ask",
    )
    new_count, new_ids = await ledger.ingest_http_fills([http_raw])

    # The HTTP fill must be recognized as the same economic execution and
    # promoted; it must not create a new fill or a new/second position.
    assert new_count == 0
    assert new_ids == []
    assert len(ledger._fills) == 1
    assert len(ledger._open_positions) == 1
    assert ledger._open_positions[key]["total_contracts"] == 1

    # The single remaining record is the authoritative (promoted) HTTP fill_id,
    # but the canonical cost basis is preserved from the live-router record.
    assert "http-fill-1" in ledger._fills
    promoted = ledger._fills["http-fill-1"]
    assert promoted.confirmed_by_rest is True
    assert promoted.canonical_position_side == "no"
    assert promoted.canonical_position_action == "buy"
    assert promoted.canonical_leg_price_cents == 52


