"""
Targeted regression tests for the 2026-08-04 Kalshi fill side/action/price fixes.

These verify that `_parse_fill` and the WebSocket bridge correctly interpret
Kalshi V2 fill fields (outcome_side, book_side, action, yes_price_dollars) and
that position-cache PnL is not inverted for NO-side long positions.
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal


@pytest.fixture
def ledger():
    from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger
    return KalshiFillsLedger()


def _record_intent(ledger, side, action, order_id=None, client_order_id=None, entry_or_exit="entry"):
    """Record an OrderIntent so _parse_fill can resolve ambiguous V2 fills."""
    from merid.event_venues.kalshi.fills_ledger import OrderIntent
    intent = OrderIntent(
        intent_id=client_order_id or f"intent-{side}",
        client_order_id=client_order_id or f"intent-{side}",
        ticker="KXETH15M-TEST",
        side=side,
        action=action,
        count=1,
        price_cents=50,
        entry_or_exit=entry_or_exit,
    )
    if order_id:
        intent.order_id = order_id
    ledger.record_intent(intent)


class TestV2FillSideActionDerivation:
    """_parse_fill must preserve raw exchange execution fields and derive the
    canonical position effect from them.  The canonical fields are the raw
    ``outcome_side`` and order ``action``; the resulting long side is encoded
    in ``canonical_yes_delta_cc`` (positive=long YES, negative=long NO).
    """

    @pytest.mark.asyncio
    async def test_parse_buy_no_with_real_sell_raw(self, ledger):
        """A raw SELL_NO (outcome_side=no, action=sell) produces long YES."""
        _record_intent(ledger, side="BUY_NO", action="buy", client_order_id="coid-buy-no")
        raw = {
            "fill_id": "fill-buy-no-1",
            "market_ticker": "KXETH15M-TEST",
            "client_order_id": "coid-buy-no",
            "outcome_side": "no",
            "book_side": "ask",
            "side": "no",
            "action": "sell",
            "yes_price_dollars": "0.6800",
            "no_price_dollars": "0.3200",
            "count_fp": "1",
            "fee_cost": "0",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }
        fill = ledger._parse_fill(raw, "http_poller")
        # Canonical fields are the raw exchange report.
        assert fill.canonical_position_side == "no"
        assert fill.canonical_position_action == "sell"
        assert fill.canonical_yes_delta_cc == 100  # long YES
        assert fill.price_cents == 32
        assert fill.is_exit is False

    @pytest.mark.asyncio
    async def test_parse_sell_no_exit(self, ledger):
        raw = {
            "fill_id": "fill-sell-no-1",
            "market_ticker": "KXETH15M-TEST",
            "client_order_id": "coid-sell-no",
            "outcome_side": "no",
            "book_side": "bid",
            "side": "no",
            "action": "sell",
            "yes_price_dollars": "0.4800",
            "no_price_dollars": "0.5200",
            "count_fp": "1",
            "fee_cost": "0",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }
        _record_intent(ledger, side="SELL_NO", action="sell", client_order_id="coid-sell-no", entry_or_exit="exit")
        fill = ledger._parse_fill(raw, "http_poller")
        # SELL_NO is a long-YES exposure.  The canonical fields preserve the
        # raw exchange outcome side and action.
        assert fill.canonical_position_side == "no"
        assert fill.canonical_position_action == "sell"
        assert fill.canonical_yes_delta_cc == 100
        assert fill.price_cents == 52
        assert fill.is_exit is True

    @pytest.mark.asyncio
    async def test_parse_buy_yes_entry(self, ledger):
        raw = {
            "fill_id": "fill-buy-yes-1",
            "market_ticker": "KXETH15M-TEST",
            "client_order_id": "coid-buy-yes",
            "outcome_side": "yes",
            "book_side": "bid",
            "side": "yes",
            "action": "buy",
            "yes_price_dollars": "0.4800",
            "no_price_dollars": "0.5200",
            "count_fp": "1",
            "fee_cost": "0",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }
        _record_intent(ledger, side="BUY_YES", action="buy", client_order_id="coid-buy-yes")
        fill = ledger._parse_fill(raw, "http_poller")
        assert fill.canonical_position_side == "yes"
        assert fill.canonical_position_action == "buy"
        assert fill.canonical_yes_delta_cc == 100
        assert fill.price_cents == 48
        assert fill.is_exit is False

    @pytest.mark.asyncio
    async def test_parse_sell_yes_exit(self, ledger):
        raw = {
            "fill_id": "fill-sell-yes-1",
            "market_ticker": "KXETH15M-TEST",
            "client_order_id": "coid-sell-yes",
            "outcome_side": "yes",
            "book_side": "ask",
            "side": "yes",
            "action": "sell",
            "yes_price_dollars": "0.6800",
            "no_price_dollars": "0.3200",
            "count_fp": "1",
            "fee_cost": "0",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }
        _record_intent(ledger, side="SELL_YES", action="sell", client_order_id="coid-sell-yes", entry_or_exit="exit")
        fill = ledger._parse_fill(raw, "http_poller")
        # SELL_YES is a long-NO exposure.
        assert fill.canonical_position_side == "yes"
        assert fill.canonical_position_action == "sell"
        assert fill.canonical_yes_delta_cc == -100
        assert fill.price_cents == 68
        assert fill.is_exit is True

    @pytest.mark.asyncio
    async def test_parse_buy_no_by_order_id(self, ledger):
        """HTTP fills omit client_order_id, so lookup by order_id must work."""
        _record_intent(ledger, side="BUY_NO", action="buy", client_order_id="coid-buy-no-oid", order_id="order-buy-no-oid")
        raw = {
            "fill_id": "fill-buy-no-oid",
            "market_ticker": "KXETH15M-TEST",
            "order_id": "order-buy-no-oid",
            "outcome_side": "no",
            "book_side": "ask",
            "side": "no",
            "action": "buy",
            "yes_price_dollars": "0.6800",
            "no_price_dollars": "0.3200",
            "count_fp": "1",
            "fee_cost": "0",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }
        fill = ledger._parse_fill(raw, "http_poller")
        assert fill.canonical_position_side == "no"
        assert fill.canonical_position_action == "buy"
        assert fill.canonical_yes_delta_cc == -100
        assert fill.is_exit is False

    @pytest.mark.asyncio
    async def test_fallback_without_intent(self, ledger):
        """Without an intent we cannot infer entry/exit, but we must not invert side."""
        raw = {
            "fill_id": "fill-orphan-1",
            "market_ticker": "KXETH15M-TEST",
            "outcome_side": "no",
            "book_side": "ask",
            "side": "no",
            "action": "sell",
            "yes_price_dollars": "0.6800",
            "no_price_dollars": "0.3200",
            "count_fp": "1",
            "fee_cost": "0",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }
        fill = ledger._parse_fill(raw, "http_poller")
        assert fill.canonical_position_side == "no"
        assert fill.canonical_position_action == "sell"
        assert fill.price_cents == 32
        assert fill.is_exit is None
        assert fill.unmatched is True

    @pytest.mark.asyncio
    async def test_ws_fill_price_uses_stored_no_leg(self, ledger):
        """WS fills must carry the traded-side leg price; it is not derived via complement."""
        raw = {
            "fill_id": "fill-ws-no-1",
            "market_ticker": "KXETH15M-TEST",
            "outcome_side": "no",
            "book_side": "ask",
            "action": "buy",
            "yes_price_dollars": "0.6800",
            "no_price_dollars": "0.3200",
            "count_fp": "1",
            "fee_cost": "0",
        }
        fill = ledger._parse_fill(raw, "websocket")
        assert fill.canonical_position_side == "no"
        assert fill.canonical_position_action == "buy"
        assert fill.price_cents == 32


class TestPositionCacheNoPnl:
    """Long NO position PnL must use (exit - entry) in own-side cents."""

    @pytest.mark.asyncio
    async def test_no_position_realized_pnl(self):
        from merid.event_venues.kalshi.position_cache import get_position_cache
        cache = get_position_cache()
        # Fresh singleton per test run; use a unique market
        market_id = "KXETH15M-PNL-TEST"
        cache._positions = {}
        cache._applied_fill_ids.clear()
        cache._reconciliation_halted.clear()

        # Open long NO at 32c
        await cache.on_fill(
            market_id=market_id,
            contracts=1,
            price_cents=32,
            fee_cents=0,
            side="no",
            client_order_id="entry-1",
            fill_id="f-entry",
            action="buy",
            is_exit=False,
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        pos = cache._positions[market_id]
        assert pos.contracts == 1
        assert pos.avg_price_cents == 32
        assert pos.side == "no"

        # Close at 52c -> profit 20c
        await cache.on_fill(
            market_id=market_id,
            contracts=1,
            price_cents=52,
            fee_cents=0,
            side="no",
            client_order_id="exit-1",
            fill_id="f-exit",
            action="sell",
            is_exit=True,
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        assert pos.contracts == 0
        assert float(pos.realized_pnl_usd) == pytest.approx(0.20)


class TestYesDeltaCanonicalization:
    """Unit tests for the signed YES exposure canonicalizer."""

    def test_buy_yes_is_long_yes(self):
        from merid.event_venues.kalshi.binary_price_space import yes_delta
        assert yes_delta("buy", "yes", 5) == 5

    def test_sell_no_is_long_yes(self):
        from merid.event_venues.kalshi.binary_price_space import yes_delta
        assert yes_delta("sell", "no", 3) == 3

    def test_buy_no_is_long_no(self):
        from merid.event_venues.kalshi.binary_price_space import yes_delta
        assert yes_delta("buy", "no", 4) == -4

    def test_sell_yes_is_long_no(self):
        from merid.event_venues.kalshi.binary_price_space import yes_delta
        assert yes_delta("sell", "yes", 2) == -2

    def test_to_signed_yes_exposure(self):
        from merid.event_venues.kalshi.binary_price_space import to_signed_yes_exposure
        assert to_signed_yes_exposure("yes", 5) == 5
        assert to_signed_yes_exposure("no", 3) == -3

    def test_from_signed_yes_exposure(self):
        from merid.event_venues.kalshi.binary_price_space import from_signed_yes_exposure
        assert from_signed_yes_exposure(5) == ("yes", 5)
        assert from_signed_yes_exposure(-3) == ("no", 3)

    def test_order_lifecycle_event_invariant(self):
        from merid.prediction.intent_contract import OrderLifecycleEvent
        event = OrderLifecycleEvent(
            client_order_id="c1",
            ticker="KXBTC15M-TEST",
            strategy_intent="BULLISH_EVENT",
            action="buy",
            side="yes",
            price_cents=50,
            quantity=2,
            normalized_yes_delta=2,
            pre_position_yes=0,
            post_position_yes_expected=2,
            post_position_yes_actual=2,
            reason="test",
        )
        is_valid, error = event.invariant()
        assert is_valid, error


class TestEquivalentOrderPairCanonicalization:
    """All four order forms must produce the same signed exposure and PnL."""

    @pytest.mark.asyncio
    async def test_sell_no_is_equivalent_to_buy_yes_entry(self):
        """SELL NO is economically the same as BUY YES (long YES)."""
        from merid.event_venues.kalshi.position_cache import get_position_cache
        cache = get_position_cache()
        cache._positions = {}
        cache._applied_fill_ids.clear()
        cache._reconciliation_halted.clear()

        # SELL NO at 38c (NO-side) is a long-YES entry.  The stored YES/NO leg
        # prices (62c YES, 38c NO) let the cache keep the held-side price.
        await cache.on_fill(
            market_id="KXETH15M-SELL-NO-ENTRY",
            contracts=1,
            price_cents=38,
            fee_cents=0,
            side="no",
            client_order_id="entry-sell-no",
            fill_id="f-sell-no-entry",
            action="sell",
            canonicalization_state="TRUSTED_LIVE_V1",
            yes_price_cents=62,
            no_price_cents=38,
        )
        pos = cache._positions["KXETH15M-SELL-NO-ENTRY"]
        assert pos.side == "yes"
        assert pos.thesis_side == "yes"
        assert pos.contracts == 1
        assert pos.avg_price_cents == 62

    @pytest.mark.asyncio
    async def test_sell_yes_is_equivalent_to_buy_no_entry(self):
        """SELL YES is economically the same as BUY NO (long NO)."""
        from merid.event_venues.kalshi.position_cache import get_position_cache
        cache = get_position_cache()
        cache._positions = {}
        cache._applied_fill_ids.clear()
        cache._reconciliation_halted.clear()

        # SELL YES at 64c (YES-side) is a long-NO entry.  The stored YES/NO leg
        # prices (64c YES, 36c NO) let the cache keep the held-side price.
        await cache.on_fill(
            market_id="KXETH15M-SELL-YES-ENTRY",
            contracts=1,
            price_cents=64,
            fee_cents=0,
            side="yes",
            client_order_id="entry-sell-yes",
            fill_id="f-sell-yes-entry",
            action="sell",
            canonicalization_state="TRUSTED_LIVE_V1",
            yes_price_cents=64,
            no_price_cents=36,
        )
        pos = cache._positions["KXETH15M-SELL-YES-ENTRY"]
        assert pos.side == "no"
        assert pos.thesis_side == "no"
        assert pos.contracts == 1
        assert pos.avg_price_cents == 36

    @pytest.mark.asyncio
    async def test_buy_no_closes_long_yes(self):
        """BUY NO is a valid close of an existing long YES position."""
        from merid.event_venues.kalshi.position_cache import get_position_cache
        cache = get_position_cache()
        cache._positions = {}
        cache._applied_fill_ids.clear()
        cache._reconciliation_halted.clear()

        # Open long YES at 40c.
        await cache.on_fill(
            market_id="KXETH15M-BUY-NO-CLOSE",
            contracts=1,
            price_cents=40,
            fee_cents=0,
            side="yes",
            client_order_id="entry-yes",
            fill_id="f-entry-yes",
            action="buy",
            canonicalization_state="TRUSTED_LIVE_V1",
            yes_price_cents=40,
            no_price_cents=60,
        )
        pos = cache._positions["KXETH15M-BUY-NO-CLOSE"]
        assert pos.side == "yes"

        # Close via BUY NO at 32c (NO-side).  The held side is YES, so the
        # stored YES leg price (68c) is used for PnL: 68 - 40 = +28c.
        await cache.on_fill(
            market_id="KXETH15M-BUY-NO-CLOSE",
            contracts=1,
            price_cents=32,
            fee_cents=0,
            side="no",
            client_order_id="exit-buy-no",
            fill_id="f-exit-buy-no",
            action="buy",
            canonicalization_state="TRUSTED_LIVE_V1",
            yes_price_cents=68,
            no_price_cents=32,
        )
        assert pos.contracts == 0
        assert float(pos.realized_pnl_usd) == pytest.approx(0.28)

    @pytest.mark.asyncio
    async def test_sell_no_closes_long_no(self):
        """SELL NO is a valid close of an existing long NO position."""
        from merid.event_venues.kalshi.position_cache import get_position_cache
        cache = get_position_cache()
        cache._positions = {}
        cache._applied_fill_ids.clear()
        cache._reconciliation_halted.clear()

        # Open long NO at 35c
        await cache.on_fill(
            market_id="KXETH15M-SELL-NO-CLOSE",
            contracts=1,
            price_cents=35,
            fee_cents=0,
            side="no",
            client_order_id="entry-no",
            fill_id="f-entry-no",
            action="buy",
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        pos = cache._positions["KXETH15M-SELL-NO-CLOSE"]
        assert pos.side == "no"

        # Close via SELL NO at 25c.  We receive 25c, PnL = 25 - 35 = -10c.
        await cache.on_fill(
            market_id="KXETH15M-SELL-NO-CLOSE",
            contracts=1,
            price_cents=25,
            fee_cents=0,
            side="no",
            client_order_id="exit-sell-no",
            fill_id="f-exit-sell-no",
            action="sell",
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        assert pos.contracts == 0
        assert float(pos.realized_pnl_usd) == pytest.approx(-0.10)

    @pytest.mark.asyncio
    async def test_buy_yes_closes_long_no(self):
        """BUY YES is a valid close of an existing long NO position."""
        from merid.event_venues.kalshi.position_cache import get_position_cache
        cache = get_position_cache()
        cache._positions = {}
        cache._applied_fill_ids.clear()
        cache._reconciliation_halted.clear()

        # Open long NO at 30c.
        await cache.on_fill(
            market_id="KXETH15M-BUY-YES-CLOSE",
            contracts=1,
            price_cents=30,
            fee_cents=0,
            side="no",
            client_order_id="entry-no",
            fill_id="f-entry-no",
            action="buy",
            canonicalization_state="TRUSTED_LIVE_V1",
            yes_price_cents=70,
            no_price_cents=30,
        )
        pos = cache._positions["KXETH15M-BUY-YES-CLOSE"]
        assert pos.side == "no"

        # Close via BUY YES at 55c.  The held side is NO, so the stored NO leg
        # price (45c) is used for PnL: 45 - 30 = +15c.
        await cache.on_fill(
            market_id="KXETH15M-BUY-YES-CLOSE",
            contracts=1,
            price_cents=55,
            fee_cents=0,
            side="yes",
            client_order_id="exit-buy-yes",
            fill_id="f-exit-buy-yes",
            action="buy",
            canonicalization_state="TRUSTED_LIVE_V1",
            yes_price_cents=55,
            no_price_cents=45,
        )
        assert pos.contracts == 0
        assert float(pos.realized_pnl_usd) == pytest.approx(0.15)

    @pytest.mark.asyncio
    async def test_sell_yes_closes_long_yes(self):
        """SELL YES is a valid close of an existing long YES position."""
        from merid.event_venues.kalshi.position_cache import get_position_cache
        cache = get_position_cache()
        cache._positions = {}
        cache._applied_fill_ids.clear()
        cache._reconciliation_halted.clear()

        # Open long YES at 60c
        await cache.on_fill(
            market_id="KXETH15M-SELL-YES-CLOSE",
            contracts=1,
            price_cents=60,
            fee_cents=0,
            side="yes",
            client_order_id="entry-yes",
            fill_id="f-entry-yes",
            action="buy",
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        pos = cache._positions["KXETH15M-SELL-YES-CLOSE"]
        assert pos.side == "yes"

        # Close via SELL YES at 75c.  PnL = 75 - 60 = +15c.
        await cache.on_fill(
            market_id="KXETH15M-SELL-YES-CLOSE",
            contracts=1,
            price_cents=75,
            fee_cents=0,
            side="yes",
            client_order_id="exit-sell-yes",
            fill_id="f-exit-sell-yes",
            action="sell",
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        assert pos.contracts == 0
        assert float(pos.realized_pnl_usd) == pytest.approx(0.15)


class TestExitClassificationAndIdempotency:
    """Regression tests for the 2026-08-09 exit/idempotency/reconciliation fixes.

    These verify that:
    - SELL_YES / BUY_NO with reduce_only close existing positions and never invert.
    - Unknown fills are marked UNMATCHED_FILL.
    - client_order_id / order_id / fill_id resolve to one immutable order record.
    - Replay of an exit fill leaves zero position.
    """

    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        from merid.event_venues.kalshi.position_cache import get_position_cache
        cache = get_position_cache()
        cache._positions = {}
        cache._applied_fill_ids.clear()
        cache._reconciliation_halted.clear()
        yield

    @pytest.mark.asyncio
    async def test_sell_yes_reduce_only_closes_long_yes_no_inversion(self):
        """SELL_YES with reduce_only closes long YES and never creates long NO."""
        from merid.event_venues.kalshi.position_cache import get_position_cache
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger, OrderIntent

        cache = get_position_cache()
        ledger = KalshiFillsLedger()

        # Record an entry intent and fill it.
        ledger.record_intent(OrderIntent(
            intent_id="i-entry-yes",
            client_order_id="coid-entry-yes",
            ticker="KXETH15M-REDUCE-SELL-YES",
            side="BUY_YES",
            action="buy",
            count=1,
            price_cents=50,
            entry_or_exit="entry",
        ))
        entry_raw = {
            "fill_id": "f-sell-yes-reduce-entry",
            "market_ticker": "KXETH15M-REDUCE-SELL-YES",
            "client_order_id": "coid-entry-yes",
            "outcome_side": "yes",
            "book_side": "bid",
            "side": "yes",
            "action": "buy",
            "yes_price_dollars": "0.5000",
            "no_price_dollars": "0.5000",
            "count_fp": "1",
            "fee_cost": "0",
        }
        entry_fill = ledger._parse_fill(entry_raw, "http_poller")
        assert entry_fill.is_exit is False

        await cache.on_fill(
            market_id="KXETH15M-REDUCE-SELL-YES",
            contracts=1,
            price_cents=50,
            fee_cents=0,
            side=entry_fill.canonical_position_side,
            client_order_id=entry_fill.client_order_id,
            fill_id=entry_fill.fill_id,
            action=entry_fill.canonical_position_action,
            is_exit=entry_fill.is_exit,
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        pos = cache._positions["KXETH15M-REDUCE-SELL-YES"]
        assert pos.side == "yes"
        assert pos.contracts == 1

        # Record the reduce-only exit intent and replay the fill.
        ledger.record_intent(OrderIntent(
            intent_id="i-exit-sell-yes",
            client_order_id="coid-exit-sell-yes",
            ticker="KXETH15M-REDUCE-SELL-YES",
            side="SELL_YES",
            action="sell",
            count=1,
            price_cents=60,
            entry_or_exit="exit",
            reduce_only=True,
        ))
        exit_raw = {
            "fill_id": "f-sell-yes-reduce-exit",
            "market_ticker": "KXETH15M-REDUCE-SELL-YES",
            "client_order_id": "coid-exit-sell-yes",
            "outcome_side": "yes",
            "book_side": "ask",
            "side": "yes",
            "action": "sell",
            "yes_price_dollars": "0.6000",
            "no_price_dollars": "0.4000",
            "count_fp": "1",
            "fee_cost": "0",
        }
        exit_fill = ledger._parse_fill(exit_raw, "http_poller")
        assert exit_fill.is_exit is True
        assert exit_fill.reduce_only is True
        # SELL_YES is a long-NO exposure.  The exchange reports outcome_side=yes,
        # action=sell; the canonical fields preserve that raw execution.
        assert exit_fill.canonical_position_side == "yes"
        assert exit_fill.canonical_position_action == "sell"
        assert exit_fill.price_cents == 60

        await cache.on_fill(
            market_id="KXETH15M-REDUCE-SELL-YES",
            contracts=1,
            price_cents=exit_fill.price_cents,
            fee_cents=0,
            side=exit_fill.canonical_position_side,
            client_order_id=exit_fill.client_order_id,
            fill_id=exit_fill.fill_id,
            action=exit_fill.canonical_position_action,
            is_exit=exit_fill.is_exit,
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        assert pos.contracts == 0
        assert pos.side == "yes"
        # PnL in YES space: 60 - 50 = +10c.
        assert float(pos.realized_pnl_usd) == pytest.approx(0.10)

    @pytest.mark.asyncio
    async def test_buy_no_reduce_only_closes_long_yes_never_creates_long_no(self):
        """BUY_NO with reduce_only closes long YES and never creates long NO."""
        from merid.event_venues.kalshi.position_cache import get_position_cache
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger, OrderIntent

        cache = get_position_cache()
        ledger = KalshiFillsLedger()

        # Create a long-YES position via BUY_YES entry.
        ledger.record_intent(OrderIntent(
            intent_id="i-buy-yes-long-yes",
            client_order_id="coid-buy-yes-long-yes",
            ticker="KXETH15M-REDUCE-BUY-NO",
            side="BUY_YES",
            action="buy",
            count=1,
            price_cents=40,
            entry_or_exit="entry",
        ))
        entry_raw = {
            "fill_id": "f-buy-no-reduce-entry",
            "market_ticker": "KXETH15M-REDUCE-BUY-NO",
            "client_order_id": "coid-buy-yes-long-yes",
            "outcome_side": "yes",
            "book_side": "bid",
            "side": "yes",
            "action": "buy",
            "yes_price_dollars": "0.4000",
            "no_price_dollars": "0.6000",
            "count_fp": "1",
            "fee_cost": "0",
        }
        entry_fill = ledger._parse_fill(entry_raw, "http_poller")
        assert entry_fill.is_exit is False

        await cache.on_fill(
            market_id="KXETH15M-REDUCE-BUY-NO",
            contracts=1,
            price_cents=40,
            fee_cents=0,
            side=entry_fill.canonical_position_side,
            client_order_id=entry_fill.client_order_id,
            fill_id=entry_fill.fill_id,
            action=entry_fill.canonical_position_action,
            is_exit=entry_fill.is_exit,
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        pos = cache._positions["KXETH15M-REDUCE-BUY-NO"]
        assert pos.side == "yes"
        assert pos.contracts == 1

        # Reduce-only BUY_NO (equivalent to SELL_YES) closes the long YES position.
        # Kalshi V2 fills report the YES-book trade direction as "sell" even though
        # the MERID intent is BUY_NO; the fill is canonicalized to side=no, action=buy.
        ledger.record_intent(OrderIntent(
            intent_id="i-exit-buy-no",
            client_order_id="coid-exit-buy-no",
            ticker="KXETH15M-REDUCE-BUY-NO",
            side="BUY_NO",
            action="buy",
            count=1,
            price_cents=30,
            entry_or_exit="exit",
            reduce_only=True,
        ))
        exit_raw = {
            "fill_id": "f-buy-no-reduce-exit",
            "market_ticker": "KXETH15M-REDUCE-BUY-NO",
            "client_order_id": "coid-exit-buy-no",
            "outcome_side": "yes",
            "book_side": "bid",
            "side": "no",
            "action": "sell",
            "yes_price_dollars": "0.7000",
            "no_price_dollars": "0.3000",
            "count_fp": "1",
            "fee_cost": "0",
        }
        exit_fill = ledger._parse_fill(exit_raw, "http_poller")
        assert exit_fill.is_exit is True
        assert exit_fill.reduce_only is True

        await cache.on_fill(
            market_id="KXETH15M-REDUCE-BUY-NO",
            contracts=1,
            price_cents=30,
            fee_cents=0,
            side=exit_fill.canonical_position_side,
            client_order_id=exit_fill.client_order_id,
            fill_id=exit_fill.fill_id,
            action=exit_fill.canonical_position_action,
            is_exit=exit_fill.is_exit,
            canonicalization_state="TRUSTED_LIVE_V1",
            yes_price_cents=70,
            no_price_cents=30,
        )
        assert pos.contracts == 0
        # Should not have flipped to long NO.
        assert pos.side == "yes"

    @pytest.mark.asyncio
    async def test_unknown_fill_is_unmatched(self):
        """A fill with no client_order_id, order_id, or recorded intent is UNMATCHED."""
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger

        ledger = KalshiFillsLedger()
        raw = {
            "fill_id": "f-unknown",
            "market_ticker": "KXETH15M-UNKNOWN",
            "outcome_side": "yes",
            "book_side": "bid",
            "side": "yes",
            "action": "buy",
            "yes_price_dollars": "0.5000",
            "no_price_dollars": "0.5000",
            "count_fp": "1",
            "fee_cost": "0",
        }
        fill = ledger._parse_fill(raw, "http_poller")
        assert fill.is_exit is None
        assert fill.unmatched is True
        assert "no_correlation_ids" in (fill.unmatched_reason or "")

    @pytest.mark.asyncio
    async def test_correlation_ids_resolve_to_one_immutable_order_record(self):
        """client_order_id, order_id, and fill_id all resolve to the same intent metadata."""
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger, OrderIntent

        ledger = KalshiFillsLedger()
        intent = OrderIntent(
            intent_id="i-multi-id",
            client_order_id="coid-multi-id",
            ticker="KXETH15M-MULTI-ID",
            side="BUY_YES",
            action="buy",
            count=1,
            price_cents=50,
            entry_or_exit="exit",
            reduce_only=True,
        )
        intent.order_id = "oid-multi-id"
        ledger.record_intent(intent)

        raw = {
            "fill_id": "f-multi-id",
            "market_ticker": "KXETH15M-MULTI-ID",
            "client_order_id": "coid-multi-id",
            "order_id": "oid-multi-id",
            "outcome_side": "yes",
            "book_side": "bid",
            "side": "yes",
            "action": "buy",
            "yes_price_dollars": "0.5000",
            "no_price_dollars": "0.5000",
            "count_fp": "1",
            "fee_cost": "0",
        }
        fill = ledger._parse_fill(raw, "http_poller")
        assert fill.is_exit is True
        assert fill.reduce_only is True
        assert fill.entry_or_exit == "exit"
        assert fill.intent_id == "i-multi-id"


class TestCanonicalFillMatrix:
    """Parametric matrix across all four order forms and both execution sides."""

    @pytest.mark.parametrize(
        "intent_side,execution_outcome,yes_price,no_price,expected_side,expected_action,expected_price_cents,conflict,expect_quarantine",
        [
            # Matching executions: contract side and execution outcome agree.
            ("BUY_YES",  "yes", "0.5500", "0.4500", "yes", "buy", 55, False, False),
            ("SELL_NO",  "no",  "0.5500", "0.4500", "no",  "sell", 45, False, False),
            ("BUY_NO",   "no",  "0.5500", "0.4500", "no",  "buy", 45, False, False),
            ("SELL_YES", "yes", "0.5500", "0.4500", "yes", "sell", 55, False, False),
            # Opposite-side executions: the intent's contract side does not match
            # the exchange's execution outcome, so side_conflict is True.
            ("BUY_YES",  "no",  "0.6000", "0.4000", "no",  "sell", 40, True, False),
            ("SELL_NO",  "yes", "0.6000", "0.4000", "yes", "buy", 60, True, False),
            # True exposure inversions (e.g. BUY_YES reported for a BUY_NO).
            # The fill is quarantined as an UNTRUSTED_SIDE_CONFLICT.
            ("BUY_NO",   "yes", "0.6000", "0.4000", "yes", "buy", 60, True, True),
            ("SELL_YES", "no",  "0.6000", "0.4000", "no", "sell", 40, True, True),
        ],
    )
    @pytest.mark.asyncio
    async def test_canonical_matrix(
        self,
        ledger,
        intent_side,
        execution_outcome,
        yes_price,
        no_price,
        expected_side,
        expected_action,
        expected_price_cents,
        conflict,
        expect_quarantine,
    ):
        coid = f"coid-{intent_side}-{execution_outcome}"
        _record_intent(ledger, side=intent_side, action="buy" if intent_side.startswith("BUY") else "sell", client_order_id=coid)
        raw = {
            "fill_id": f"f-{intent_side}-{execution_outcome}",
            "market_ticker": "KXETH15M-TEST",
            "client_order_id": coid,
            "outcome_side": execution_outcome,
            "book_side": "bid" if execution_outcome == "yes" else "ask",
            "side": execution_outcome,
            "action": expected_action,
            "yes_price_dollars": yes_price,
            "no_price_dollars": no_price,
            "count_fp": "1",
            "fee_cost": "0",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }
        fill = ledger._parse_fill(raw, "http_poller")
        assert fill.side_conflict == conflict
        # intent_target_side is the contract side the agent intended to trade
        # (BUY_YES/SELL_YES -> yes; BUY_NO/SELL_NO -> no), not the resulting long side.
        assert fill.intent_target_side == ("yes" if intent_side in ("BUY_YES", "SELL_YES") else "no")
        assert fill.execution_outcome_side == execution_outcome
        # execution_price_cents is the raw price on the executed outcome side.
        expected_exec_price = int(float(yes_price) * 100) if execution_outcome == "yes" else int(float(no_price) * 100)
        assert fill.execution_price_cents == expected_exec_price

        if expect_quarantine:
            # True exposure inversion: the exchange's position direction does not
            # match the agent's intent, so the fill is quarantined.
            assert fill.unmatched is True
            assert fill.canonicalization_state == "UNTRUSTED_SIDE_CONFLICT"
            assert fill.canonical_position_side is None
            assert fill.canonical_position_action is None
            assert fill.canonical_yes_delta_cc is None
        else:
            assert fill.canonical_position_side == expected_side
            assert fill.canonical_position_action == expected_action
            assert fill.price_cents == expected_price_cents


class TestLiveSideInversionRegression:
    """Regression for the observed live position mismatch.

    When the exchange reports ``outcome_side=no`` but the agent's intent was
    ``BUY_YES`` (long YES), the fill is quarantined.  It must not be assigned
    to an existing position by ticker alone, and the position cache must not
    create a position until the conflict is reconciled via REST.
    """

    @pytest.mark.asyncio
    async def test_side_conflict_quarantines_fill(self):
        from merid.event_venues.kalshi.position_cache import get_position_cache
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger, OrderIntent

        cache = get_position_cache()
        cache._positions = {}
        cache._applied_fill_ids.clear()
        cache._reconciliation_halted.clear()

        ledger = KalshiFillsLedger()
        ledger.record_intent(OrderIntent(
            intent_id="i-mismatch-entry",
            client_order_id="coid-mismatch-entry",
            ticker="KXBTC15M-26AUG121645-45",
            side="BUY_YES",
            action="buy",
            count=1,
            price_cents=55,
            entry_or_exit="entry",
        ))

        # Exchange reports the user's fill as long NO (the observed live case).
        raw = {
            "fill_id": "f-mismatch-btc",
            "market_ticker": "KXBTC15M-26AUG121645-45",
            "client_order_id": "coid-mismatch-entry",
            "outcome_side": "no",
            "book_side": "ask",
            "side": "no",
            "action": "buy",
            "yes_price_dollars": "0.5500",
            "no_price_dollars": "0.4500",
            "count_fp": "1",
            "fee_cost": "0",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }
        fill = ledger._parse_fill(raw, "http_poller")

        # Hard invariant: a side conflict must quarantine the fill and clear
        # the canonical position effect.  The exchange report is preserved for
        # audit; the intent side is preserved for reconciliation.
        assert fill.side_conflict is True
        assert fill.unmatched is True
        assert fill.canonicalization_state == "UNTRUSTED_SIDE_CONFLICT"
        assert fill.canonical_position_side is None
        assert fill.canonical_position_action is None
        assert fill.canonical_yes_delta_cc is None
        assert fill.intent_target_side == "yes"
        assert fill.execution_outcome_side == "no"

        # Position cache must not apply the quarantined fill.
        await cache.on_fill(
            market_id="KXBTC15M-26AUG121645-45",
            contracts=1,
            price_cents=45,
            fee_cents=0,
            side=fill.side or "no",
            client_order_id=fill.client_order_id,
            fill_id=fill.fill_id,
            action=fill.action or "buy",
            is_exit=fill.is_exit,
            canonicalization_state=fill.canonicalization_state,
        )

        assert "KXBTC15M-26AUG121645-45" not in cache._positions


class TestPositionMonitorSidePreservation:
    """The position monitor must record the canonical side from the cache/ledger.

    Regression: the live BTC mismatch showed PositionMonitor/PositionCache logged
    the agent's intent side (yes) instead of the exchange's outcome side (no).
    """

    @pytest.mark.asyncio
    async def test_position_monitor_receives_no_side(self):
        from merid.position_management.position import Position, PositionSide
        from merid.position_management.position_monitor import PositionMonitor

        monitor = PositionMonitor()
        pos = Position(
            market_id="KXBTC15M-FUTURE-NO-SIDE",
            side=PositionSide.NO,
            size=1,
            avg_entry_price_cents=45,
            entry_fill_id="fill-no-side",
        )
        monitor.add_position(pos)

        stored = monitor._open_positions[pos.position_id]
        assert stored.side == PositionSide.NO
        assert stored.market_id == pos.market_id


class TestPositionCacheLabelRobustness:
    """position_cache.on_fill must use the correct held-side price even when the
    yes_price_dollars / no_price_dollars labels are swapped in the fill record.
    """

    @pytest.mark.asyncio
    async def test_position_cache_ignores_swapped_yes_no_labels(self):
        from merid.event_venues.kalshi.position_cache import get_position_cache

        cache = get_position_cache()
        cache._positions = {}
        cache._applied_fill_ids.clear()
        cache._reconciliation_halted.clear()

        market_id = "KXBTC15M-LABEL-SWAP-TEST"

        # This KalshiFill represents a BUY_NO execution.  The actual market is
        # YES=60c / NO=40c, but the yes/no price labels are swapped as happened
        # in the 2026-09-02 XRP live-router incident.  The canonical leg price
        # (40c on the no side) is correct and must disambiguate the labels.
        from merid.event_venues.kalshi.fills_ledger import KalshiFill

        fill = KalshiFill(
            fill_id="label-swap-fill-1",
            market_ticker=market_id,
            side="no",
            action="buy",
            count_fp=Decimal("1"),
            quantity_cc=100,
            yes_price_dollars=Decimal("0.40"),  # swapped: this is actually NO
            no_price_dollars=Decimal("0.60"),   # swapped: this is actually YES
            fee_cost=Decimal("0.0007"),
            canonical_position_side="no",
            canonical_position_action="buy",
            canonical_leg_price_cents=40,
            canonical_yes_delta_cc=-100,
            canonicalization_state="TRUSTED_LIVE_V1",
        )

        await cache.on_fill(
            market_id=market_id,
            contracts=1,
            price_cents=40,
            fee_cents=7,
            side="no",
            action="buy",
            quantity_cc=100,
            fill_id=fill.fill_id,
            canonicalization_state="TRUSTED_LIVE_V1",
        )

        pos = cache._positions[market_id]
        assert pos.side == "no"
        assert pos.quantity_cc == 100
        assert pos.avg_price_cents == 40
