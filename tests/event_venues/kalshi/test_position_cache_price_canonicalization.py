"""
Position cache price canonicalization tests.

These tests protect against the 2026-08-29 NO-position avg_price_cents bug
where the cache was flipping REST-reported NO prices via 100 - price or
overriding REST with a fill-derived complement.  REST must remain authoritative
and all prices must stay in the position's own outcome space.
"""

import pytest
from decimal import Decimal
from types import SimpleNamespace

from merid.event_venues.kalshi.position_cache import (
    KalshiPositionCache,
    CachedPosition,
    _is_expired_ticker,
    _is_test_ticker,
    _fill_position_side_price_cents,
)


@pytest.fixture(autouse=True)
async def _clear_cache(monkeypatch):
    """Reset the singleton cache and neutralize environment checks."""
    monkeypatch.setattr("merid.event_venues.kalshi.position_cache._is_expired_ticker", lambda t: False)
    monkeypatch.setattr("merid.event_venues.kalshi.position_cache._is_test_ticker", lambda t: False)
    cache = KalshiPositionCache()
    await cache.clear()
    cache._last_sync = None
    cache._last_rest_sync_timestamp = 0.0
    yield
    await cache.clear()
    cache._last_sync = None
    cache._last_rest_sync_timestamp = 0.0


class TestRestAvgPriceAuthority:
    """REST-provided avg_price_cents must be used as-is, never complemented."""

    @pytest.mark.asyncio
    async def test_sync_from_rest_uses_no_avg_price_unflipped(self):
        """A long NO position with REST avg_price_cents=37 must stay 37."""
        cache = KalshiPositionCache()
        market_id = "KXBTC15M-CANON-NO"

        await cache.sync_from_rest(
            positions=[
                {
                    "market_id": market_id,
                    "quantity_cc": 100,
                    "side": "no",
                    "avg_price_cents": 37,
                }
            ],
            force=True,
        )

        pos = cache._positions[market_id]
        assert pos.side == "no"
        assert pos.thesis_side == "no"
        assert pos.contracts == 1
        assert pos.avg_price_cents == 37, (
            f"REST NO avg_price_cents was flipped: got {pos.avg_price_cents}, expected 37"
        )

    @pytest.mark.asyncio
    async def test_sync_from_rest_uses_yes_avg_price_unflipped(self):
        """A long YES position with REST avg_price_cents=63 must stay 63."""
        cache = KalshiPositionCache()
        market_id = "KXBTC15M-CANON-YES"

        await cache.sync_from_rest(
            positions=[
                {
                    "market_id": market_id,
                    "quantity_cc": 100,
                    "side": "yes",
                    "avg_price_cents": 63,
                }
            ],
            force=True,
        )

        pos = cache._positions[market_id]
        assert pos.side == "yes"
        assert pos.thesis_side == "yes"
        assert pos.contracts == 1
        assert pos.avg_price_cents == 63


class TestFillPositionSidePrice:
    """Stored YES/NO leg prices select the held-side price; no complement."""

    def test_fill_position_side_price_prefers_stored_leg(self):
        fill = SimpleNamespace(
            yes_price_dollars=Decimal("0.59"),
            no_price_dollars=Decimal("0.41"),
            canonical_position_side="yes",
            canonical_leg_price_cents=None,
            side="yes",
            price_cents=59,
        )
        assert _fill_position_side_price_cents(fill, "no") == 41
        assert _fill_position_side_price_cents(fill, "yes") == 59

    def test_fill_position_side_price_no_complement_on_missing_leg(self):
        fill = SimpleNamespace(
            yes_price_dollars=Decimal("0.59"),
            no_price_dollars=None,
            canonical_position_side="yes",
            canonical_leg_price_cents=None,
            side="yes",
            price_cents=59,
        )
        # No NO price is stored and we must not synthesize one.
        assert _fill_position_side_price_cents(fill, "no") is None


class TestCachedPositionApplyFillCrossLeg:
    """Cross-leg fills use the stored opposite-leg price, not 100 - side."""

    def test_sell_yes_opens_long_no_with_stored_leg_prices(self):
        """SELL_YES at a YES price of 59c opens a long NO position at 41c."""
        pos = CachedPosition(
            market_id="KXBTC15M-CROSS",
            agent_id="test",
            thesis_side="no",
            contracts=0,
            side="no",
            avg_price_cents=0,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0"),
        )
        pos.apply_fill(
            contracts=1,
            price_cents=59,
            fee_cents=0,
            side="yes",
            action="sell",
            yes_price_cents=59,
            no_price_cents=41,
        )
        assert pos.contracts == 1
        assert pos.side == "no"
        # Held-side price must be the NO leg price, not 100 - 59.
        assert pos.avg_price_cents == 41

    def test_buy_no_closes_long_yes_with_stored_leg_prices(self):
        """BUY_NO at 40c closes a long YES position; the YES leg price is 60c."""
        pos = CachedPosition(
            market_id="KXBTC15M-CROSS",
            agent_id="test",
            thesis_side="yes",
            contracts=1,
            side="yes",
            avg_price_cents=50,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0"),
        )
        pos.apply_fill(
            contracts=1,
            price_cents=40,
            fee_cents=0,
            side="no",
            action="buy",
            yes_price_cents=60,
            no_price_cents=40,
        )
        assert pos.contracts == 0
        # PnL uses the position-side exit price (YES = 60c) minus entry (50c)
        assert float(pos.realized_pnl_usd) == pytest.approx(0.10)


class TestCachedPositionProceedsBasedPnL:
    """Authoritative signed cash proceeds drive realized PnL, not leg-price math."""

    def test_sell_no_long_yes_pnl_uses_proceeds(self):
        """SELL_NO (long YES) at 66c, then BUY_NO to close at 34c = -32c loss."""
        pos = CachedPosition(
            market_id="KXBTC15M-PROCEEDS",
            agent_id="test",
            thesis_side="yes",
            contracts=0,
            side="yes",
            avg_price_cents=0,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0"),
        )
        # Entry: SELL_NO 0.26 contracts at 66c, fee 0.00164
        pos.apply_fill(
            contracts=1,
            price_cents=66,
            fee_cents=0,
            side="no",
            action="sell",
            yes_price_cents=34,
            no_price_cents=66,
            proceeds_dollars=Decimal("0.66"),
        )
        assert pos.side == "yes"
        assert pos.quantity_cc == 100

        # Exit: BUY_NO 1 contract at 66c (position side is YES, so price is 34c),
        # but the authoritative proceeds are -0.34 (gross) - fee.
        pos.apply_fill(
            contracts=1,
            price_cents=34,
            fee_cents=0,
            side="no",
            action="buy",
            yes_price_cents=34,
            no_price_cents=66,
            proceeds_dollars=Decimal("-0.34"),
        )
        assert pos.contracts == 0
        # entry_cash_proceeds (+0.66) + close_proceeds (-0.34) = +0.32
        assert float(pos.realized_pnl_usd) == pytest.approx(0.32)

    def test_buy_yes_long_yes_pnl_uses_proceeds_with_fee(self):
        """BUY_YES at 25c, then SELL_YES at 9.6c = -15.4c gross loss, minus fee."""
        pos = CachedPosition(
            market_id="KXBTC15M-PROCEEDS-FEE",
            agent_id="test",
            thesis_side="yes",
            contracts=0,
            side="yes",
            avg_price_cents=0,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0"),
        )
        pos.apply_fill(
            contracts=1,
            price_cents=25,
            fee_cents=0,
            side="yes",
            action="buy",
            yes_price_cents=25,
            no_price_cents=75,
            proceeds_dollars=Decimal("-0.25"),
        )
        pos.apply_fill(
            contracts=1,
            price_cents=9,
            fee_cents=1,
            side="yes",
            action="sell",
            yes_price_cents=9,
            no_price_cents=91,
            proceeds_dollars=Decimal("0.08"),  # 0.09 - 0.01 fee
        )
        assert pos.contracts == 0
        # -0.25 entry + 0.08 close = -0.17
        assert float(pos.realized_pnl_usd) == pytest.approx(-0.17)

    def test_partial_close_uses_proportional_cost_basis(self):
        """A partial close allocates the correct fraction of entry proceeds."""
        pos = CachedPosition(
            market_id="KXBTC15M-PARTIAL",
            agent_id="test",
            thesis_side="yes",
            contracts=2,
            side="yes",
            avg_price_cents=50,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0"),
        )
        pos.entry_cash_proceeds_usd = Decimal("-1.00")  # 2 contracts at 50c

        # Sell 1 contract at 60c, proceeds +0.60
        pos.apply_fill(
            contracts=1,
            price_cents=60,
            fee_cents=0,
            side="yes",
            action="sell",
            yes_price_cents=60,
            no_price_cents=40,
            proceeds_dollars=Decimal("0.60"),
        )
        assert pos.quantity_cc == 100
        # half of -1.00 cost = -0.50; realized = 0.60 + (-0.50) = 0.10
        assert float(pos.realized_pnl_usd) == pytest.approx(0.10)
        assert float(pos.entry_cash_proceeds_usd) == pytest.approx(-0.50)
