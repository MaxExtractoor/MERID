"""
Production-symptom regression tests for the 15m Kalshi crypto stack.

These encode the exact failure modes that triggered the 2026-08-27/28
audit and must remain green after restart/replay:

1. Counterparty-form duplicate fills (same fill_id, different reported
   side/action from live-router vs HTTP replay) collapse to a single
   mutation and leave the position flat.
2. NO-side cost basis is derived from the position's own outcome space;
   the API ``avg_price`` that is the YES-complement of that cost basis is
   rejected.
3. A fully-closed position is removed from the position monitor and any
   subsequent exit intent is blocked with ``close_with_zero_position``.
"""

import types
from decimal import Decimal

import pytest

from merid.event_venues.kalshi.order_intent_contract import (
    OrderIntentValidationError,
    normalize_order,
    validate_canonical_intent,
)


@pytest.fixture
def cache():
    """Return a reset position-cache singleton for idempotency tests."""
    from merid.event_venues.kalshi.position_cache import get_position_cache
    c = get_position_cache()
    c._positions = {}
    c._applied_fill_ids.clear()
    c._reconciliation_halted.clear()
    yield c


class TestCounterpartyFormDuplicateFill:
    """A live-router NO/Sell fill and an HTTP-reported YES/Buy fill with the
    same fill_id must apply exactly once and leave the position flat.
    """

    @pytest.mark.asyncio
    async def test_counterparty_form_exit_is_idempotent(self, cache):
        """Long NO position is closed once by SELL NO; the duplicate BUY YES
        report of the same execution is ignored.
        """
        market_id = "KXBTC15M-REG-01"

        # Open a long NO position: BUY NO at 35c (yes_exposure = -100)
        await cache.on_fill(
            market_id=market_id,
            contracts=1,
            quantity_cc=100,
            price_cents=35,
            fee_cents=0,
            side="no",
            action="buy",
            client_order_id="entry-no",
            fill_id="f-entry-no",
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        pos = cache.get_position(market_id)
        assert pos is not None
        assert pos.quantity_cc == 100
        assert pos.side == "no"

        # Live-router close of the long NO: SELL NO at 25c flips yes_exposure to 0
        await cache.on_fill(
            market_id=market_id,
            contracts=1,
            quantity_cc=100,
            price_cents=25,
            fee_cents=0,
            side="no",
            action="sell",
            client_order_id="exit-no",
            fill_id="f-exit-1",
            is_exit=True,
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        assert cache.get_position(market_id) is None

        # HTTP replay of the same execution, reported in counterparty form:
        # BUY YES at 75c is also a long-NO exit (yes_exposure = +100 on -100).
        # Same fill_id, so it must not re-apply.
        await cache.on_fill(
            market_id=market_id,
            contracts=1,
            quantity_cc=100,
            price_cents=75,
            fee_cents=0,
            side="yes",
            action="buy",
            client_order_id="exit-yes-replay",
            fill_id="f-exit-1",
            is_exit=True,
            canonicalization_state="TRUSTED_LIVE_V1",
        )

        # The cache must still be flat and must have applied only two distinct fills.
        assert cache.get_position(market_id) is None
        assert "f-entry-no" in cache._applied_fill_ids
        assert "f-exit-1" in cache._applied_fill_ids
        assert len(cache._applied_fill_ids) == 2

    @pytest.mark.asyncio
    async def test_counterparty_form_closes_to_monitor_removable(self, cache):
        """A long NO position closed by SELL NO is removed from the PositionMonitor;
        the duplicate BUY YES replay does not re-add it.
        """
        from merid.position_management.position_monitor import get_position_monitor

        market_id = "KXBTC15M-REG-02"
        monitor = get_position_monitor()

        # Open long NO
        await cache.on_fill(
            market_id=market_id,
            contracts=1,
            quantity_cc=100,
            price_cents=35,
            fee_cents=0,
            side="no",
            action="buy",
            client_order_id="entry-no-2",
            fill_id="f-entry-no-2",
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        assert cache.get_position(market_id) is not None
        assert monitor.get_position_by_market(market_id) is not None

        # Close via live-router SELL NO
        await cache.on_fill(
            market_id=market_id,
            contracts=1,
            quantity_cc=100,
            price_cents=25,
            fee_cents=0,
            side="no",
            action="sell",
            client_order_id="exit-no-2",
            fill_id="f-exit-2",
            is_exit=True,
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        assert cache.get_position(market_id) is None
        assert monitor.get_position_by_market(market_id) is None

        # Replay as BUY YES (same fill_id) must not re-add
        await cache.on_fill(
            market_id=market_id,
            contracts=1,
            quantity_cc=100,
            price_cents=75,
            fee_cents=0,
            side="yes",
            action="buy",
            client_order_id="exit-yes-2",
            fill_id="f-exit-2",
            is_exit=True,
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        assert cache.get_position(market_id) is None
        assert monitor.get_position_by_market(market_id) is None


class TestNoCostBasisComplementGuard:
    """``KalshiClient._parse_position`` must derive the NO-side own-price and
    reject a YES-complement ``avg_price`` from the API.
    """

    def _client(self):
        from merid.event_venues.kalshi.client import KalshiVenueClient
        # __new__ avoids credential/env initialization; _parse_position is stateless.
        return KalshiVenueClient.__new__(KalshiVenueClient)

    def test_parse_position_returns_own_side_avg_for_long_no(self):
        client = self._client()
        data = {
            "ticker": "KXBTC15M-TEST",
            "position_fp": "-1.00",
            # Side intentionally omitted: negative position_fp with no side is
            # the Kalshi convention for a long-NO position in this parser.
            "market_exposure_dollars": "0.58",
            "avg_price": "42",  # complement of the true 58c own-side cost
            "created_at": None,
        }
        pos = client._parse_position(data)
        assert pos is not None
        assert pos.side == "no"
        assert pos.count == 1
        assert float(pos.avg_price) == pytest.approx(58.0)

    def test_parse_position_rejects_complement_avg_price(self):
        """When cost-derived price is 58c and API avg_price is the complement 42c,
        the final price stays at 58c (complement is rejected).
        """
        client = self._client()
        data = {
            "ticker": "KXBTC15M-TEST",
            "position_fp": "-1.00",
            "market_exposure_dollars": "0.58",
            "avg_price": "42",
            "created_at": None,
        }
        pos = client._parse_position(data)
        assert pos is not None
        assert float(pos.avg_price) == pytest.approx(58.0)

    def test_parse_position_uses_avg_price_when_consistent_with_cost(self):
        """When cost-derived price and API avg_price agree within 1c, keep the API value."""
        client = self._client()
        data = {
            "ticker": "KXBTC15M-TEST",
            "position_fp": "-1.00",
            "market_exposure_dollars": "0.58",
            "avg_price": "57.5",
            "created_at": None,
        }
        pos = client._parse_position(data)
        assert pos is not None
        assert float(pos.avg_price) == pytest.approx(57.5)


class TestPostExitRearmSuppression:
    """After a position is fully closed it must not re-arm exits."""

    @pytest.mark.asyncio
    async def test_exit_intent_blocked_after_position_closed(self, cache):
        """A closed position cannot generate a new exit order."""
        market_id = "KXBTC15M-REG-03"

        await cache.on_fill(
            market_id=market_id,
            contracts=1,
            quantity_cc=100,
            price_cents=45,
            fee_cents=0,
            side="yes",
            action="buy",
            client_order_id="entry-yes-3",
            fill_id="f-entry-yes-3",
            canonicalization_state="TRUSTED_LIVE_V1",
        )

        await cache.on_fill(
            market_id=market_id,
            contracts=1,
            quantity_cc=100,
            price_cents=55,
            fee_cents=0,
            side="yes",
            action="sell",
            client_order_id="exit-yes-3",
            fill_id="f-exit-3",
            is_exit=True,
            canonicalization_state="TRUSTED_LIVE_V1",
        )

        assert cache.get_position(market_id) is None

        # Any exit intent submitted after the position is flat must fail closed.
        intent = types.SimpleNamespace(
            ticker=market_id,
            side="yes",
            action="sell",
            price_cents=55,
            count=1,
            source="agent_grid_15m",
            entry_or_exit="exit",
            reduce_only=False,
            is_exit_order=True,
            kalshi_side=None,
            pre_position_size=None,
            expected_post_position_size=None,
            allow_short=None,
            rationale=None,
            exit_reason=None,
            estimated_fee_cents=0,
            expected_realized_pnl_cents=None,
            intent_id="test-exit-post-close",
            client_order_id="test-exit-post-close",
            time_to_expiry_seconds=900.0,
        )
        c = normalize_order(intent, exchange_position_cc=0)
        with pytest.raises(OrderIntentValidationError, match="close_with_zero_position"):
            validate_canonical_intent(c, exchange_position_cc=0)

    @pytest.mark.asyncio
    async def test_position_monitor_removes_closed_position(self, cache):
        """KalshiPositionCache must remove a closed position from PositionMonitor."""
        from merid.position_management.position_monitor import get_position_monitor

        market_id = "KXBTC15M-REG-04"
        monitor = get_position_monitor()

        await cache.on_fill(
            market_id=market_id,
            contracts=1,
            quantity_cc=100,
            price_cents=45,
            fee_cents=0,
            side="yes",
            action="buy",
            client_order_id="entry-yes-4",
            fill_id="f-entry-yes-4",
            canonicalization_state="TRUSTED_LIVE_V1",
        )
        assert monitor.get_position_by_market(market_id) is not None

        await cache.on_fill(
            market_id=market_id,
            contracts=1,
            quantity_cc=100,
            price_cents=55,
            fee_cents=0,
            side="yes",
            action="sell",
            client_order_id="exit-yes-4",
            fill_id="f-exit-4",
            is_exit=True,
            canonicalization_state="TRUSTED_LIVE_V1",
        )

        assert cache.get_position(market_id) is None
        assert monitor.get_position_by_market(market_id) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
