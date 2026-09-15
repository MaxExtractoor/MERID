"""
Regression tests for live-router provisional fill promotion.

The authoritative HTTP/WS fill overlays the provisional record.  When the
provisional live-router fill was written in counterparty wire form (e.g. SELL_NO)
while the exchange reports the held-side form (BUY_YES), the promoted record must
adopt the authoritative canonical side/action so the canonical leg price and
signed cash proceeds are computed from the user's actual held side.  This
prevents counterparty-form fills from flipping position cost basis and realized
PnL.
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
        # Authoritative trusted canonical side/action overwrite the provisional
        # counterparty form so realized PnL uses the held side (YES).
        assert promoted_fill.canonical_position_side == "yes"
        assert promoted_fill.canonical_position_action == "buy"
        # Authoritative market legs overlay the provisional record.
        assert promoted_fill.yes_price_dollars == Decimal("0.34")
        assert promoted_fill.no_price_dollars == Decimal("0.66")
        # Canonical leg price is in the user's outcome space (BUY_YES = 34c).
        assert promoted_fill.canonical_leg_price_cents == 34
        # Signed YES delta stays +54 (long YES / short NO).
        assert promoted_fill.canonical_yes_delta_cc == 54
        # Proceeds are recomputed using the user's held side/action and fee.
        # 0.34 * 0.54 + 0.0085 = 0.1921 -> signed -0.1921 for a buy
        assert promoted_fill.proceeds_dollars == pytest.approx(Decimal("-0.1921"))

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


class TestCanonicalBackfill:
    """_backfill_canonical_from_raw repairs stale persisted rows on load."""

    @pytest.mark.asyncio
    async def test_backfill_fixes_counterparty_form_eth_exit(self, ledger):
        order_id = "01a0a43c-6e78-7601-9879-0c4bbfaba834"
        fill_id = "072234de-56a1-acb1-d4cc-e5484ade41e1"

        # Stale row as persisted by an older build: it recorded the exchange's
        # raw counterparty form (side=no, action=sell, no_price=0.015) instead
        # of the user's held-side form (BUY_YES at 98.5c).
        raw_payload = {
            "fill_id": fill_id,
            "trade_id": fill_id,
            "order_id": order_id,
            "client_order_id": "exit_a4d8202cf2ad9f5806fc",
            "market_ticker": "KXETH15M-26SEP150445-45",
            "ticker": "KXETH15M-26SEP150445-45",
            "market_id": "KXETH15M-26SEP150445-45",
            "action": "buy",
            "side": "yes",
            "outcome_side": "yes",
            "count": "0.04",
            "count_fp": "0.04",
            "quantity_cc": 4,
            "yes_price_dollars": "0.9850",
            "no_price_dollars": "0.0150",
            "price": "0.9850",
            "price_dollars": "0.9850",
            "fee": "0.000100",
            "fee_paid": "0.000100",
            "timestamp": 1789461819.299435,
            "created_time": "2026-09-15T08:43:39.299435Z",
            "ingested_at": "2026-09-15T08:43:51.647671Z",
            "source": "http_poller",
        }

        stale_fill = KalshiFill(
            fill_id=fill_id,
            trade_id=fill_id,
            order_id=order_id,
            market_ticker="KXETH15M-26SEP150445-45",
            side="no",
            action="sell",
            count_fp=Decimal("0.04"),
            quantity_cc=4,
            yes_price_dollars=Decimal("0.985"),
            no_price_dollars=Decimal("0.015"),
            fee_cost=Decimal("0.0001"),
            proceeds_dollars=Decimal("0.0005"),
            client_order_id="exit_a4d8202cf2ad9f5806fc",
            client_tag="exit_a4d8202cf2ad9f5806fc",
            is_exit=True,
            reduce_only=True,
            execution_outcome_side="no",
            execution_action="sell",
            execution_price_cents=2,
            canonical_position_side="no",
            canonical_position_action="sell",
            canonical_leg_price_cents=2,
            canonical_yes_delta_cc=4,
            canonicalization_state="TRUSTED_LIVE_V1",
            canonicalization_version=1,
            ledger_schema_version=3,
            raw_payload=raw_payload,
            ingestion_source="http_poller",
            created_time=datetime.now(timezone.utc),
        )

        ledger._fills[fill_id] = stale_fill

        changed = await ledger._backfill_canonical_from_raw()
        assert changed == 1

        fixed = ledger._fills[fill_id]
        assert fixed.side == "yes"
        assert fixed.action == "buy"
        assert fixed.canonical_position_side == "yes"
        assert fixed.canonical_position_action == "buy"
        assert fixed.canonical_leg_price_cents == 99
        assert fixed.canonical_yes_delta_cc == 4
        # Signed cash proceeds for a 0.04 BUY_YES at 98.5c with 0.01c fee.
        assert fixed.proceeds_dollars == pytest.approx(Decimal("-0.0395"))
        assert fixed.canonicalization_version == 2

    @pytest.mark.asyncio
    async def test_backfill_skips_up_to_date_rows(self, ledger):
        fill = KalshiFill(
            fill_id="up_to_date",
            market_ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            count_fp=Decimal("0.1"),
            quantity_cc=10,
            yes_price_dollars=Decimal("0.5"),
            no_price_dollars=Decimal("0.5"),
            fee_cost=Decimal("0.0001"),
            proceeds_dollars=Decimal("-0.0501"),
            canonical_position_side="yes",
            canonical_position_action="buy",
            canonical_leg_price_cents=50,
            canonical_yes_delta_cc=10,
            canonicalization_state="TRUSTED_LIVE_V1",
            canonicalization_version=2,
            ledger_schema_version=3,
            raw_payload={"fill_id": "up_to_date"},
            ingestion_source="http_poller",
            created_time=datetime.now(timezone.utc),
        )
        ledger._fills["up_to_date"] = fill

        changed = await ledger._backfill_canonical_from_raw()
        assert changed == 0
