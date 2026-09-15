"""
Regression tests for live-router provisional fill promotion.

When the exchange reports a fill in counterparty form (e.g. BUY_YES for a user
SELL_NO order), the authoritative HTTP/WS fill must overlay the *prices* while
preserving the user's canonical side/action.  The promoted record's canonical
leg price and signed cash proceeds must be recomputed from the authoritative
market legs and the user's intended contract form.
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal

from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger, KalshiFill


@pytest.fixture
def ledger():
    return KalshiFillsLedger()


def _make_provisional(order_id: str, fill_id: str = "live_router_test_0") -> KalshiFill:
    """A provisional live-router fill with the user's SELL_NO intent."""
    return KalshiFill(
        fill_id=fill_id,
        order_id=order_id,
        market_ticker="KXDOGE15M-TEST",
        side="no",
        action="sell",
        count_fp=Decimal("0.54"),
        quantity_cc=54,
        yes_price_dollars=Decimal("0.66"),  # wrong provisional orientation
        no_price_dollars=Decimal("0.34"),
        fee_cost=Decimal("0.01"),
        proceeds_dollars=Decimal("0.1736"),  # 0.34 * 0.54 - 0.01 (wrong)
        canonical_position_side="no",
        canonical_position_action="sell",
        canonical_leg_price_cents=34,
        canonical_yes_delta_cc=54,
        canonicalization_state="TRUSTED_LIVE_V1",
        is_live=True,
        created_time=datetime.now(timezone.utc),
    )


def _make_authoritative(order_id: str, fill_id: str = "auth_fill_0") -> KalshiFill:
    """Authoritative exchange fill in counterparty BUY_YES form."""
    return KalshiFill(
        fill_id=fill_id,
        order_id=order_id,
        market_ticker="KXDOGE15M-TEST",
        side="yes",
        action="buy",
        count_fp=Decimal("0.54"),
        quantity_cc=54,
        yes_price_dollars=Decimal("0.34"),
        no_price_dollars=Decimal("0.66"),
        fee_cost=Decimal("0.0085"),
        proceeds_dollars=Decimal("-0.1921"),  # raw counterparty proceeds
        execution_outcome_side="yes",
        execution_action="buy",
        execution_price_cents=34,
        canonical_position_side="yes",
        canonical_position_action="buy",
        canonical_leg_price_cents=34,
        canonical_yes_delta_cc=54,
        canonicalization_state="TRUSTED_LIVE_V1",
        is_live=True,
        created_time=datetime.now(timezone.utc),
    )


class TestLiveRouterPromotion:
    """_promote_live_router_fill must preserve user side and recompute economics."""

    @pytest.mark.asyncio
    async def test_promotion_preserves_user_side_and_recomputes_prices(self, ledger):
        order_id = "order-doge-01"
        prov = _make_provisional(order_id)
        auth = _make_authoritative(order_id)

        ledger._fills[prov.fill_id] = prov
        ledger._live_router_fill_ids[order_id] = prov.fill_id

        promoted = ledger._promote_live_router_fill(auth)
        assert promoted == auth.fill_id

        promoted_fill = ledger._fills[auth.fill_id]
        assert promoted_fill.canonical_position_side == "no"
        assert promoted_fill.canonical_position_action == "sell"
        # Authoritative market legs overlay the provisional record.
        assert promoted_fill.yes_price_dollars == Decimal("0.34")
        assert promoted_fill.no_price_dollars == Decimal("0.66")
        # Canonical leg price is in the user's outcome space (NO = 66c).
        assert promoted_fill.canonical_leg_price_cents == 66
        # Signed YES delta stays +54 (long YES / short NO).
        assert promoted_fill.canonical_yes_delta_cc == 54
        # Proceeds are recomputed using the user's side/action and authoritative fee.
        # 0.66 * 0.54 - 0.0085 = 0.3479
        assert promoted_fill.proceeds_dollars == pytest.approx(Decimal("0.3479"))

    @pytest.mark.asyncio
    async def test_promotion_without_order_id_is_noop(self, ledger):
        auth = _make_authoritative("order-orphan")
        assert ledger._promote_live_router_fill(auth) is None

    @pytest.mark.asyncio
    async def test_promotion_economic_mismatch_is_noop(self, ledger):
        order_id = "order-doge-02"
        prov = _make_provisional(order_id)
        prov.quantity_cc = 99  # quantity differs
        ledger._fills[prov.fill_id] = prov
        ledger._live_router_fill_ids[order_id] = prov.fill_id

        auth = _make_authoritative(order_id)
        assert ledger._promote_live_router_fill(auth) is None
