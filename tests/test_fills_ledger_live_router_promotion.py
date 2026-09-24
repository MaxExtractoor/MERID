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

from merid.event_venues.kalshi.fills_ledger import (
    KalshiFillsLedger,
    KalshiFill,
    CANONICALIZATION_VERSION,
)


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
    async def test_promotion_direction_conflict_is_noop(self, ledger):
        """An authoritative fill with opposite signed exposure cannot belong to
        the order — a single Kalshi order fills in one direction only."""
        order_id = "order-doge-02"
        prov = _make_provisional(order_id)
        ledger._fills[prov.fill_id] = prov
        ledger._live_router_fill_ids[order_id] = prov.fill_id

        auth = _make_authoritative(order_id)
        auth.canonical_yes_delta_cc = -54  # opposite signed exposure
        assert ledger._promote_live_router_fill(auth) is None

    @pytest.mark.asyncio
    async def test_promotion_overfill_is_noop(self, ledger):
        """An authoritative fill larger than the provisional total is not a
        partial — it cannot be reconciled with the order."""
        order_id = "order-doge-03"
        prov = _make_provisional(order_id)  # delta +54
        ledger._fills[prov.fill_id] = prov
        ledger._live_router_fill_ids[order_id] = prov.fill_id

        auth = _make_authoritative(order_id)
        auth.quantity_cc = 99
        auth.count_fp = Decimal("0.99")
        auth.canonical_yes_delta_cc = 99  # same direction but exceeds provisional
        assert ledger._promote_live_router_fill(auth) is None


class TestPartialFillPromotion:
    """The 2026-09-24 phantom-position fix.

    Kalshi reports one order's execution as multiple trade records.  A 100cc
    provisional followed by 90cc + 10cc counterparty-form authoritative fills
    must collapse to the same single position mutation: the first partial
    promotes the provisional row; every further partial is a ledger-only
    sibling whose signed delta never reaches the position cache.
    """

    def _make_provisional_buy_no(self, order_id: str) -> KalshiFill:
        """Provisional BUY NO 100cc (canonical no/buy, delta -100)."""
        return KalshiFill(
            fill_id=f"live_router_{order_id}_0",
            order_id=order_id,
            market_ticker="KXXRP15M-TEST",
            side="no",
            action="buy",
            count_fp=Decimal("1.0"),
            quantity_cc=100,
            yes_price_dollars=Decimal("0.30"),
            no_price_dollars=Decimal("0.70"),
            fee_cost=Decimal("0.02"),
            proceeds_dollars=Decimal("-0.72"),
            canonical_position_side="no",
            canonical_position_action="buy",
            canonical_leg_price_cents=70,
            canonical_yes_delta_cc=-100,
            canonicalization_state="TRUSTED_LIVE_V1",
            is_live=True,
            created_time=datetime.now(timezone.utc),
        )

    def _make_auth_sell_yes_partial(
        self, order_id: str, fill_id: str, qty_cc: int, yes_cents: int
    ) -> KalshiFill:
        """Authoritative partial in counterparty SELL YES form.

        The user's BUY NO fill arrives from the exchange as SELL YES; trusted
        canonicalization resolves the intent side (no/buy) while the wire legs
        carry the YES execution price.
        """
        return KalshiFill(
            fill_id=fill_id,
            trade_id=fill_id,
            order_id=order_id,
            market_ticker="KXXRP15M-TEST",
            side="yes",
            action="sell",
            count_fp=Decimal(qty_cc) / Decimal("100"),
            quantity_cc=qty_cc,
            yes_price_dollars=Decimal(yes_cents) / Decimal("100"),
            no_price_dollars=Decimal(100 - yes_cents) / Decimal("100"),
            fee_cost=Decimal("0.005"),
            proceeds_dollars=Decimal(qty_cc) * Decimal(yes_cents) / Decimal("10000"),
            execution_outcome_side="yes",
            execution_action="sell",
            execution_price_cents=yes_cents,
            canonical_position_side="no",
            canonical_position_action="buy",
            canonical_leg_price_cents=100 - yes_cents,
            canonical_yes_delta_cc=-qty_cc,
            canonicalization_state="TRUSTED_LIVE_V1",
            is_live=True,
            created_time=datetime.now(timezone.utc),
        )

    @pytest.mark.asyncio
    async def test_first_partial_promotes_and_updates_quantity(self, ledger):
        order_id = "order-xrp-01"
        prov = self._make_provisional_buy_no(order_id)
        ledger._fills[prov.fill_id] = prov
        ledger._live_router_fill_ids[order_id] = prov.fill_id

        p1 = self._make_auth_sell_yes_partial(order_id, "auth_p1", 90, 30)
        promoted = ledger._promote_live_router_fill(p1)
        assert promoted == "auth_p1"

        row = ledger._fills["auth_p1"]
        # Authoritative quantity replaces the provisional total.
        assert row.quantity_cc == 90
        assert row.count_fp == Decimal("0.90")
        # Canonical delta recomputed from the preserved user side/action.
        assert row.canonical_position_side == "no"
        assert row.canonical_position_action == "buy"
        assert row.canonical_yes_delta_cc == -90
        # Canonical leg stays in the user's NO space (100 - 30 = 70).
        assert row.canonical_leg_price_cents == 70
        # Coverage metadata records the provisional total for reconciliation.
        assert row.raw_payload["provisional_quantity_cc"] == 100
        assert row.raw_payload["authoritative_coverage_cc"] == 90

    @pytest.mark.asyncio
    async def test_second_partial_is_ledger_only_sibling(self, ledger):
        order_id = "order-xrp-02"
        prov = self._make_provisional_buy_no(order_id)
        ledger._fills[prov.fill_id] = prov
        ledger._live_router_fill_ids[order_id] = prov.fill_id

        p1 = self._make_auth_sell_yes_partial(order_id, "auth_p1", 90, 30)
        assert ledger._promote_live_router_fill(p1) == "auth_p1"

        p2 = self._make_auth_sell_yes_partial(order_id, "auth_p2", 10, 31)
        consumed = ledger._promote_live_router_fill(p2)
        # The canonical row id is returned — the sibling is consumed.
        assert consumed == "auth_p1"
        # The sibling is a durable ledger row (audit + replay), marked consumed.
        assert "auth_p2" in ledger._fills
        assert "auth_p2" in ledger._processed_fill_ids
        assert getattr(p2, "_consumed_by_provisional", False) is True
        # Aggregate coverage now matches the provisional total.
        row = ledger._fills["auth_p1"]
        assert row.raw_payload["authoritative_coverage_cc"] == 100
        assert "auth_p2" in row.raw_payload["sibling_fill_ids"]

    @pytest.mark.asyncio
    async def test_redelivery_is_idempotent(self, ledger):
        order_id = "order-xrp-03"
        prov = self._make_provisional_buy_no(order_id)
        ledger._fills[prov.fill_id] = prov
        ledger._live_router_fill_ids[order_id] = prov.fill_id

        p1 = self._make_auth_sell_yes_partial(order_id, "auth_p1", 90, 30)
        assert ledger._promote_live_router_fill(p1) == "auth_p1"
        # Re-delivery of the same fill id must not re-merge or re-apply.
        p1b = self._make_auth_sell_yes_partial(order_id, "auth_p1", 90, 30)
        assert ledger._promote_live_router_fill(p1b) == "auth_p1"
        row = ledger._fills["auth_p1"]
        assert row.quantity_cc == 90
        assert row.raw_payload["authoritative_coverage_cc"] == 90

    @pytest.mark.asyncio
    async def test_conflicting_direction_sibling_is_quarantined(self, ledger):
        order_id = "order-xrp-04"
        prov = self._make_provisional_buy_no(order_id)  # delta -100
        ledger._fills[prov.fill_id] = prov
        ledger._live_router_fill_ids[order_id] = prov.fill_id

        p1 = self._make_auth_sell_yes_partial(order_id, "auth_p1", 90, 30)
        assert ledger._promote_live_router_fill(p1) == "auth_p1"

        # A "sibling" reporting +delta on the same order is impossible on a
        # single-sided order — quarantine rather than apply.
        bad = self._make_auth_sell_yes_partial(order_id, "auth_bad", 10, 31)
        bad.canonical_yes_delta_cc = 10  # opposite sign
        consumed = ledger._promote_live_router_fill(bad)
        assert consumed == "auth_p1"
        assert bad.unmatched is True
        assert bad.unmatched_reason == "provisional_sibling_direction_conflict"
        assert getattr(bad, "_consumed_by_provisional", False) is True


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
        assert fixed.canonicalization_version == CANONICALIZATION_VERSION

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
            canonicalization_version=CANONICALIZATION_VERSION,
            ledger_schema_version=3,
            raw_payload={"fill_id": "up_to_date"},
            ingestion_source="http_poller",
            created_time=datetime.now(timezone.utc),
        )
        ledger._fills["up_to_date"] = fill

        changed = await ledger._backfill_canonical_from_raw()
        assert changed == 0
