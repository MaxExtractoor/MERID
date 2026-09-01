"""Fractional contract, centi-contract canonical, and replay-safety tests.

These verify the 2026-08-09 V2 fixed-point migration:
- `KalshiFill` preserves fractional sizes as `count_fp` (Decimal) and `quantity_cc` (int).
- `fills_ledger.compute_position_from_fills` and `position_cache.on_fill` use `quantity_cc`.
- Replay of the same `fill_id` is idempotent.
- HTTP-poller replay of an exit fill cannot re-open a closed position.
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal

from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger, OrderIntent
from merid.event_venues.kalshi.position_cache import KalshiPositionCache
from merid.event_venues.kalshi.port_ledger_adapter import (
    port_fill_to_ledger_dict,
    port_position_to_ledger_dict,
)


@pytest.fixture
def ledger():
    return KalshiFillsLedger()


@pytest.fixture
def cache():
    c = KalshiPositionCache()
    c._positions = {}
    c._applied_fill_ids.clear()
    c._reconciliation_halted.clear()
    return c


def _record_intent(ledger, side, action, client_order_id, entry_or_exit="entry"):
    intent = OrderIntent(
        intent_id=client_order_id,
        client_order_id=client_order_id,
        ticker="KXETH15M-TEST",
        side=side,
        action=action,
        count=1,
        price_cents=50,
        entry_or_exit=entry_or_exit,
    )
    ledger.record_intent(intent)


def _make_fill_dict(
    fill_id,
    client_order_id,
    side,
    action,
    count,
    yes_price_dollars="0.5000",
    no_price_dollars="0.5000",
):
    return {
        "fill_id": fill_id,
        "market_ticker": "KXETH15M-TEST",
        "client_order_id": client_order_id,
        "outcome_side": side,
        "side": side,
        "action": action,
        "yes_price_dollars": yes_price_dollars,
        "no_price_dollars": no_price_dollars,
        "count_fp": str(count),
        "fee_cost": "0",
        "created_time": datetime.now(timezone.utc).isoformat(),
    }


class TestFractionalFillParsing:
    """`_parse_fill` must preserve fractional `count_fp` and derive `quantity_cc`."""

    @pytest.mark.asyncio
    async def test_parse_buy_yes_half_contract(self, ledger):
        _record_intent(ledger, "BUY_YES", "buy", "coid-half")
        raw = _make_fill_dict(
            "fill-half",
            "coid-half",
            "yes",
            "buy",
            "0.49",
            yes_price_dollars="0.2000",
            no_price_dollars="0.8000",
        )
        fill = ledger._parse_fill(raw, "http_poller")
        assert fill.count_fp == Decimal("0.49")
        assert fill.quantity_cc == 49
        assert fill.price_cents == 20

    @pytest.mark.asyncio
    async def test_parse_buy_no_one_and_a_half_contracts(self, ledger):
        _record_intent(ledger, "BUY_NO", "buy", "coid-one-half")
        raw = _make_fill_dict(
            "fill-one-half",
            "coid-one-half",
            "no",
            "sell",
            "1.55",
            yes_price_dollars="0.3500",
            no_price_dollars="0.6500",
        )
        fill = ledger._parse_fill(raw, "http_poller")
        assert fill.count_fp == Decimal("1.55")
        assert fill.quantity_cc == 155
        assert fill.price_cents == 65


class TestFractionalPositionMath:
    """Ledger and cache exposure math must use `quantity_cc`, not display contracts."""

    @pytest.mark.asyncio
    async def test_compute_position_from_fills_fractional(self, ledger):
        _record_intent(ledger, "BUY_NO", "buy", "coid-frac-entry")
        raw_entry = _make_fill_dict(
            "fill-frac-entry",
            "coid-frac-entry",
            "no",
            "buy",
            "0.49",
            yes_price_dollars="0.4000",
            no_price_dollars="0.6000",
        )
        fill = ledger._parse_fill(raw_entry, "http_poller")
        ledger._fills[fill.fill_id] = fill
        ledger._index_fill(fill)

        pos = ledger.compute_position_from_fills("KXETH15M-TEST")
        assert pos is not None
        assert pos["side"] == "no"
        assert pos["quantity_cc"] == 49
        assert pos["contracts"] == Decimal("0.49")

    @pytest.mark.asyncio
    async def test_position_cache_on_fill_fractional(self, cache):
        await cache.on_fill(
            market_id="KXETH15M-TEST",
            contracts=0,
            quantity_cc=49,
            price_cents=60,
            fee_cents=0,
            side="no",
            action="buy",
            fill_id="fill-frac",
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        pos = cache.get_position("KXETH15M-TEST")
        assert pos is not None
        assert pos.quantity_cc == 49
        assert pos.contracts == 0  # display floor
        assert pos._yes_exposure() == -49

    @pytest.mark.asyncio
    async def test_position_cache_fractional_exit_pnl(self, cache):
        # Entry 0.49 contract long NO @ 60c
        await cache.on_fill(
            market_id="KXETH15M-TEST",
            contracts=0,
            quantity_cc=49,
            price_cents=60,
            fee_cents=0,
            side="no",
            action="buy",
            fill_id="fill-frac-entry",
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        pos = cache.get_position("KXETH15M-TEST")
        assert pos is not None
        # Exit via SELL_NO (same as BUY_YES economically) @ 55c
        await cache.on_fill(
            market_id="KXETH15M-TEST",
            contracts=0,
            quantity_cc=49,
            price_cents=55,
            fee_cents=0,
            side="no",
            action="sell",
            fill_id="fill-frac-exit",
            is_exit=True,
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        # The cache deletes the closed position, but the object reference still holds the PnL.
        assert pos.quantity_cc == 0
        # PnL for long NO: (exit - entry) in own-side cents = (55 - 60) * 0.49 = -2.45 cents = -0.0245 USD
        assert pos.realized_pnl_usd == Decimal("-0.0245")


class TestFillReplaySafety:
    """Replayed fills must be idempotent and exits must not become entries."""

    @pytest.mark.asyncio
    async def test_duplicate_fill_id_is_idempotent(self, cache):
        await cache.on_fill(
            market_id="KXETH15M-TEST",
            contracts=1,
            quantity_cc=100,
            price_cents=50,
            fee_cents=0,
            side="yes",
            action="buy",
            fill_id="fill-dup",
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        # Same fill_id replayed
        await cache.on_fill(
            market_id="KXETH15M-TEST",
            contracts=1,
            quantity_cc=100,
            price_cents=50,
            fee_cents=0,
            side="yes",
            action="buy",
            fill_id="fill-dup",
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        pos = cache.get_position("KXETH15M-TEST")
        assert pos.quantity_cc == 100

    @pytest.mark.asyncio
    async def test_http_poller_replay_of_exit_does_not_reopen(self, cache):
        # Entry
        await cache.on_fill(
            market_id="KXETH15M-TEST",
            contracts=1,
            quantity_cc=100,
            price_cents=50,
            fee_cents=0,
            side="yes",
            action="buy",
            fill_id="fill-entry",
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        # Exit
        await cache.on_fill(
            market_id="KXETH15M-TEST",
            contracts=1,
            quantity_cc=100,
            price_cents=60,
            fee_cents=0,
            side="yes",
            action="sell",
            fill_id="fill-exit",
            is_exit=True,
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        # Replay same exit via HTTP poller
        await cache.on_fill(
            market_id="KXETH15M-TEST",
            contracts=1,
            quantity_cc=100,
            price_cents=60,
            fee_cents=0,
            side="yes",
            action="sell",
            fill_id="fill-exit",
            is_exit=True,
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        pos = cache.get_position("KXETH15M-TEST")
        assert pos is None or pos.quantity_cc == 0


class TestPortLedgerAdapterFractional:
    """Port DTOs must expose `quantity_cc` for fractional sizes."""

    def test_port_position_fractional_size(self):
        from merid.event_venues.kalshi.venue_client_port import Position

        pos = Position(
            ticker="KXETH15M-TEST",
            outcome="yes",
            size=Decimal("1.55"),
            average_entry_price_cents=48,
        )
        result = port_position_to_ledger_dict(pos)
        assert result["quantity_cc"] == 155
        assert result["contracts"] == 1  # display floor

    def test_port_fill_fractional_size(self):
        from merid.event_venues.kalshi.port import Fill

        fill = Fill(
            fill_id="fill-frac",
            order_id="order-frac",
            ticker="KXETH15M-TEST",
            side="buy",
            outcome="yes",
            size=Decimal("0.49"),
            price_cents=20,
            fee_usd=Decimal("0"),
            timestamp=datetime.now(timezone.utc),
        )
        result = port_fill_to_ledger_dict(fill)
        assert result["quantity_cc"] == 49
        assert result["count_fp"] == "0.49"


class TestFillFeeAudit:
    """Per-fill fee audit record captures gross, fee, and net economics."""

    @pytest.mark.asyncio
    async def test_fill_fee_audit_computes_net_price(self, ledger, caplog):
        from merid.event_venues.kalshi.fills_ledger import KalshiFill

        fill = KalshiFill(
            fill_id="fill-fee-audit-01",
            order_id="order-fee-audit-01",
            client_order_id="coid-fee-audit-01",
            market_ticker="KXETH15M-TEST",
            market_id="KXETH15M-TEST",
            canonical_position_side="yes",
            canonical_position_action="buy",
            side="yes",
            action="buy",
            count_fp=Decimal("2"),
            quantity_cc=200,
            yes_price_dollars=Decimal("0.5500"),
            no_price_dollars=Decimal("0.4500"),
            fee_cost=Decimal("0.14"),  # 2 contracts * 7c taker fee
            canonicalization_state="TRUSTED_LIVE_V1",
        )

        ledger._fills[fill.fill_id] = fill
        ledger._index_fill(fill)
        ledger._emit_fill_fee_audit(fill)

        assert fill.fee_cost_cents == 14
        assert fill.fee_per_contract_cents == Decimal("7")
        assert fill.net_price_cents == Decimal("62")

        # The structured audit record should be in the log extra dict.
        audit_records = [
            r for r in caplog.records
            if "[FILL-FEE-AUDIT]" in r.getMessage()
        ]
        assert len(audit_records) == 1
        audit = audit_records[0].fill_fee_audit
        assert audit["fill_id"] == fill.fill_id
        assert audit["gross_price_cents"] == 55
        assert audit["fee_cost_cents"] == 14
        assert audit["fee_per_contract_cents"] == 7.0
        assert audit["net_price_cents"] == 62.0
        assert audit["order_id"] == "order-fee-audit-01"
        assert audit["client_order_id"] == "coid-fee-audit-01"


class TestXRPReplayEndToEnd:
    """End-to-end XRP replay: BUY_NO at 41c, SELL_NO at 5c, verify PnL and flat ledger."""

    @pytest.mark.asyncio
    async def test_xrp_sell_no_exit_canonicalizes_and_pnl(self, ledger, cache):
        # Link cache to the ledger so the live fill path uses canonical records.
        cache._fills_ledger = ledger

        # Entry intent: long NO 1 contract @ 41c (yes=59, no=41).
        entry_intent = OrderIntent(
            intent_id="coid-xrp-entry",
            client_order_id="coid-xrp-entry",
            ticker="KXXRP15M-TEST",
            side="BUY_NO",
            action="buy",
            count=1,
            price_cents=41,
            entry_or_exit="entry",
        )
        ledger.record_intent(entry_intent)

        raw_entry = _make_fill_dict(
            "xrp-entry-1",
            "coid-xrp-entry",
            "no",
            "buy",
            "1",
            yes_price_dollars="0.5900",
            no_price_dollars="0.4100",
        )
        fill_entry = ledger._parse_fill(raw_entry, "http_poller")
        ledger._fills[fill_entry.fill_id] = fill_entry
        ledger._index_fill(fill_entry)

        # Cache should open a long NO position with entry price in NO space.
        await cache.on_fill(
            market_id="KXXRP15M-TEST",
            contracts=1,
            quantity_cc=100,
            price_cents=fill_entry.price_cents,
            fee_cents=0,
            side="no",
            action="buy",
            fill_id=fill_entry.fill_id,
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        pos = cache.get_position("KXXRP15M-TEST")
        assert pos is not None
        assert pos.side == "no"
        assert pos.avg_price_cents == 41
        assert pos.quantity_cc == 100

        # Exit intent: SELL_NO 1 contract @ 5c (yes=95, no=5) to close the long NO.
        exit_intent = OrderIntent(
            intent_id="coid-xrp-exit",
            client_order_id="coid-xrp-exit",
            ticker="KXXRP15M-TEST",
            side="SELL_NO",
            action="sell",
            count=1,
            price_cents=5,
            entry_or_exit="exit",
            reduce_only=True,
        )
        ledger.record_intent(exit_intent)

        raw_exit = _make_fill_dict(
            "xrp-exit-1",
            "coid-xrp-exit",
            "no",
            "sell",
            "1",
            yes_price_dollars="0.9500",
            no_price_dollars="0.0500",
        )
        fill_exit = ledger._parse_fill(raw_exit, "http_poller")
        ledger._fills[fill_exit.fill_id] = fill_exit
        ledger._index_fill(fill_exit)

        await cache.on_fill(
            market_id="KXXRP15M-TEST",
            contracts=1,
            quantity_cc=100,
            price_cents=fill_exit.price_cents,
            fee_cents=0,
            side="no",
            action="sell",
            fill_id=fill_exit.fill_id,
            is_exit=True,
            canonicalization_state="TRUSTED_LIVE_V1",
        )

        # Position should be fully closed; realized PnL is the NO-side loss.
        assert pos.quantity_cc == 0
        assert pos.realized_pnl_usd == Decimal("-0.36")

        # Ledger-derived position must be flat after the exit.
        ledger_pos = ledger.compute_position_from_fills("KXXRP15M-TEST")
        assert ledger_pos is None
